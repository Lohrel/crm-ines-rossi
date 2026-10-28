from datetime import date, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apolices.forms import (
    ContratoForm,
    DocumentoDaSeguradoraForm,
    FiltroContratosForm,
    ImovelForm,
    PlanoForm,
    SeguradoraForm,
    VeiculoForm,
)
from apolices.historico import LinhaDoTempoDaSeguradora, LinhaDoTempoDoBem
from apolices.models import (
    DIAS_PARA_RENOVACAO,
    BemSegurado,
    Contrato,
    DocumentoDaSeguradora,
    Plano,
    Seguradora,
    TipoDeBem,
    limpar_placa,
)
from beneficiarios.models import Vinculo
from beneficiarios.vidas import anotar_vidas
from boletos.models import Boleto
from clientes.forms import SecaoDoFormulario
from clientes.models import Cliente
from clientes.views import (
    ArquivoAnexadoCreateView,
    ArquivoAnexadoDeleteView,
    ExclusaoConfirmadaView,
    FormularioMixin,
    entregar_arquivo,
)


class ContratoListView(ListView):
    """Todos os contratos, com filtros por seguradora, ramo, situação, vencimento e renovação."""

    model = Contrato
    paginate_by = 50
    template_name = "apolices/contratos.html"

    def get_queryset(self):
        self.filtro = FiltroContratosForm(self.request.GET or None)
        contratos = anotar_vidas(
            Contrato.objects.select_related("cliente", "seguradora", "ramo").prefetch_related(
                "bens", "planos"
            )
        )
        if not self.filtro.is_valid():
            return contratos.vigentes()
        dados = self.filtro.cleaned_data
        situacao = dados["situacao"]
        if situacao == "":
            contratos = contratos.vigentes()
        elif situacao != "todas":
            contratos = contratos.filter(situacao=situacao)
        if termo := dados["q"].strip():
            filtro = (
                Q(numero__icontains=termo)
                | Q(produto__icontains=termo)
                | Q(cliente__nome__icontains=termo)
                | Q(pk__in=Plano.objects.filter(nome__icontains=termo).values("contrato"))
            )
            # A placa é guardada sem o traço e em maiúsculas; ela sempre tem números.
            placa = limpar_placa(termo)
            if len(placa) >= 3 and any(caractere.isdigit() for caractere in placa):
                com_a_placa = BemSegurado.objects.filter(placa__contains=placa)
                filtro |= Q(pk__in=com_a_placa.values("contrato"))
            contratos = contratos.filter(filtro)
        if dados["seguradora"]:
            contratos = contratos.filter(seguradora=dados["seguradora"])
        if dados["ramo"]:
            contratos = contratos.filter(ramo=dados["ramo"])
        if dados["boleto"]:
            contratos = contratos.com_boleto_da_corretora()
        if dados["vencimento"]:
            contratos = contratos.filter(dia_vencimento=dados["vencimento"])
        if dados["renovacao"]:
            limite = date.today() + timedelta(days=DIAS_PARA_RENOVACAO)
            contratos = contratos.renovam_ate(limite).order_by("data_renovacao", "cliente__nome")
        return contratos

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["filtro"] = self.filtro
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


SECAO_DO_SEGURO_DE_VIDA = "Só para seguro de vida: capital e fatura de cada vida"


class SecoesDoContratoMixin:
    """Os campos do seguro de vida (capital e fatura) ficam num cartão à parte."""

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        form = contexto["form"]
        vida = Contrato.CAMPOS_DO_SEGURO_DE_VIDA
        outros = [nome for nome in form.fields if nome not in vida]
        contexto["formularios"] = [
            ("", SecaoDoFormulario(form, outros, principal=True)),
            (SECAO_DO_SEGURO_DE_VIDA, SecaoDoFormulario(form, vida)),
        ]
        return contexto


class ContratoCreateView(SecoesDoContratoMixin, FormularioMixin, CreateView):
    model = Contrato
    form_class = ContratoForm
    mensagem_sucesso = "Contrato cadastrado."

    def get_cliente(self) -> Cliente:
        return get_object_or_404(Cliente, pk=self.kwargs["cliente_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.get_cliente()}

    def get_titulo(self) -> str:
        return f"Novo contrato de {self.get_cliente()}"

    def get_url_cancelar(self) -> str:
        return self.get_cliente().get_absolute_url()


class ContratoUpdateView(SecoesDoContratoMixin, FormularioMixin, UpdateView):
    model = Contrato
    form_class = ContratoForm
    mensagem_sucesso = "Contrato atualizado."

    def form_valid(self, form):
        resposta = super().form_valid(form)
        self._acompanhar_boletos(self.object, set(form.changed_data))
        return resposta

    def _acompanhar_boletos(self, contrato: Contrato, mudou: set[str]) -> None:
        """Ajusta ao contrato as mensalidades a enviar já geradas para os próximos meses."""
        if "situacao" in mudou and contrato.situacao == Contrato.Situacao.CANCELADO:
            quantas = Boleto.cancelar_com_o_contrato(contrato)
            singular, plural = "foi cancelada", "foram canceladas"
            texto = "dos próximos meses {} junto com o contrato."
        elif "dia_vencimento" in mudou:
            quantas = Boleto.seguir_novo_vencimento(contrato)
            singular, plural = "passou", "passaram"
            texto = "{} para o novo vencimento."
        else:
            return
        if quantas == 1:
            messages.info(self.request, "1 mensalidade a enviar " + texto.format(singular))
        elif quantas:
            messages.info(self.request, f"{quantas} mensalidades a enviar " + texto.format(plural))

    def get_titulo(self) -> str:
        return f"Editar contrato {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class ContratoDeleteView(ExclusaoConfirmadaView):
    """Exclui um contrato cadastrado por engano; com pessoas ou movimentações, não deixa."""

    model = Contrato
    permission_required = "apolices.delete_contrato"
    dica_bloqueio = (
        "Pessoas, movimentações e boletos são o histórico da carteira e não são apagados com o "
        "contrato. Se o contrato deixou de valer, edite e mude a situação para Cancelado. "
        "Se as pessoas também foram cadastradas por teste, exclua cada uma na página dela. "
        "Numa pendência, basta editar e tirar o contrato."
    )

    def get_queryset(self):
        return Contrato.objects.select_related("cliente", "seguradora")

    def get_aviso(self) -> str:
        avisos = []
        for relacao, um, varios in [
            ("planos", "O plano cadastrado será excluído", "Os {} planos serão excluídos"),
            ("subfaturas", "A subfatura (SUB) será excluída", "As {} subfaturas serão excluídas"),
            (
                "bens",
                "O veículo ou imóvel será excluído",
                "Os {} veículos e imóveis serão excluídos",
            ),
        ]:
            if quantos := getattr(self.object, relacao).count():
                frase = um if quantos == 1 else varios.format(quantos)
                avisos.append(f"{frase} junto com o contrato.")
        if quantos := self.object.documentos.count():
            avisos.append(
                "O documento anexado ao cliente continua lá, sem a ligação com o contrato."
                if quantos == 1
                else f"Os {quantos} documentos anexados ao cliente continuam lá, "
                "sem a ligação com o contrato."
            )
        return " ".join(avisos)

    def get_success_url(self) -> str:
        return f"{self.object.cliente.get_absolute_url()}#contratos"


class ContratoPlanosView(DetailView):
    """Os planos de um contrato (ex.: TNPQ e TNP4), as vidas de cada um e o plano de quem
    ainda não tem um escolhido."""

    template_name = "apolices/planos.html"
    context_object_name = "contrato"

    def get_queryset(self):
        return (
            Contrato.objects.de_pessoas()
            .select_related("cliente", "seguradora", "ramo")
            .prefetch_related("planos")
        )

    def sem_plano(self):
        """Quem está no contrato hoje (ou entra depois) e ainda não tem o plano escolhido."""
        return (
            Vinculo.objects.filter(contrato=self.object, plano__isnull=True)
            .filter(Q(data_exclusao__isnull=True) | Q(data_exclusao__gt=date.today()))
            .select_related("beneficiario__titular", "beneficiario__unidade")
            .order_by(
                # Cada família junta: o titular e, logo abaixo, os dependentes.
                Coalesce("beneficiario__titular__nome", "beneficiario__nome"),
                F("beneficiario__titular").asc(nulls_first=True),
                "beneficiario__nome",
            )
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contrato = self.object
        vidas = dict(
            Vinculo.objects.ativos()
            .filter(contrato=contrato)
            .values_list("plano")
            .annotate(total=Count("pk"))
            .order_by()
        )
        planos = list(contrato.planos.all())
        for plano in planos:
            plano.vidas = vidas.get(plano.pk, 0)
        sem_plano = list(self.sem_plano())
        # O dependente começa com o plano do titular marcado.
        do_titular = dict(
            Vinculo.objects.filter(
                contrato=contrato,
                plano__isnull=False,
                data_exclusao__isnull=True,
                beneficiario__in=[v.beneficiario.titular_id for v in sem_plano],
            ).values_list("beneficiario", "plano")
        )
        for vinculo in sem_plano:
            vinculo.sugerido = do_titular.get(vinculo.beneficiario.titular_id)
        contexto.update(
            planos=planos,
            vidas_sem_plano=vidas.get(None, 0),
            sem_plano=sem_plano,
            form=PlanoForm(contrato=contrato),
        )
        return contexto

    def post(self, request, *args, **kwargs):
        """Grava o plano escolhido para cada pessoa que ainda não tinha um."""
        self.object = self.get_object()
        ativos = {str(plano.pk): plano for plano in self.object.planos_ativos}
        escolhidos = 0
        with transaction.atomic():
            vinculos = list(self.sem_plano().select_for_update(of=("self",)))
            # Os titulares primeiro, para o dependente marcado "o mesmo do titular" achar o
            # plano que acabou de ser escolhido para ele.
            vinculos.sort(key=lambda vinculo: not vinculo.beneficiario.eh_titular)
            for vinculo in vinculos:
                escolha = request.POST.get(f"plano_{vinculo.pk}", "")
                if escolha == "titular" and not vinculo.beneficiario.eh_titular:
                    do_titular = Vinculo.objects.filter(
                        contrato=self.object,
                        beneficiario=vinculo.beneficiario.titular_id,
                        data_exclusao__isnull=True,
                    ).values_list("plano", flat=True)
                    escolha = str(do_titular.first() or "")
                plano = ativos.get(escolha)
                if plano:
                    vinculo.plano = plano
                    vinculo.save(update_fields=["plano", "atualizado_em"])
                    escolhidos += 1
        if escolhidos:
            texto = "1 pessoa" if escolhidos == 1 else f"{escolhidos} pessoas"
            messages.success(request, f"Plano gravado para {texto}.")
        else:
            messages.info(request, "Nenhum plano foi escolhido.")
        return redirect("apolices:planos", self.object.pk)


class PlanoCreateView(FormularioMixin, CreateView):
    model = Plano
    form_class = PlanoForm
    mensagem_sucesso = "Plano cadastrado."

    def get_contrato(self) -> Contrato:
        if not hasattr(self, "contrato"):
            self.contrato = get_object_or_404(
                Contrato.objects.de_pessoas(), pk=self.kwargs["contrato_pk"]
            )
        return self.contrato

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "contrato": self.get_contrato()}

    def get_titulo(self) -> str:
        return f"Novo plano no contrato {self.get_contrato()}"

    def get_url_cancelar(self) -> str:
        return reverse("apolices:planos", args=[self.get_contrato().pk])


class PlanoUpdateView(FormularioMixin, UpdateView):
    model = Plano
    form_class = PlanoForm
    mensagem_sucesso = "Plano atualizado."

    def get_titulo(self) -> str:
        return f"Editar o plano {self.object} do contrato {self.object.contrato}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class SeguradoraListView(ListView):
    model = Seguradora
    template_name = "apolices/seguradoras.html"

    def get_queryset(self):
        return Seguradora.objects.annotate(total_de_documentos=Count("documentos"))


class SeguradoraDetailView(DetailView):
    """Dados da seguradora, os documentos dela (regras de produto, tabelas...) e o histórico."""

    model = Seguradora
    template_name = "apolices/seguradora.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["documentos"] = self.object.documentos.select_related("enviado_por", "ramo")
        contexto["historico"] = LinhaDoTempoDaSeguradora(self.object).eventos()
        return contexto


class SeguradoraCreateView(FormularioMixin, CreateView):
    model = Seguradora
    form_class = SeguradoraForm
    titulo = "Nova seguradora"
    mensagem_sucesso = "Seguradora cadastrada."

    def get_url_cancelar(self) -> str:
        return reverse("apolices:seguradoras")


class SeguradoraUpdateView(FormularioMixin, UpdateView):
    model = Seguradora
    form_class = SeguradoraForm
    mensagem_sucesso = "Seguradora atualizada."

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class DocumentoDaSeguradoraCreateView(ArquivoAnexadoCreateView):
    model = DocumentoDaSeguradora
    modelo_do_dono = Seguradora
    form_class = DocumentoDaSeguradoraForm


def baixar_documento_da_seguradora(request, pk: int):
    return entregar_arquivo(request, get_object_or_404(DocumentoDaSeguradora, pk=pk))


class DocumentoDaSeguradoraDeleteView(ArquivoAnexadoDeleteView):
    model = DocumentoDaSeguradora
    permission_required = "apolices.delete_documentodaseguradora"


FORMULARIOS_DOS_BENS = {TipoDeBem.VEICULO: VeiculoForm, TipoDeBem.IMOVEL: ImovelForm}


def url_dos_bens(cliente: Cliente) -> str:
    """O cartão "Veículos e imóveis segurados" na página do cliente."""
    return f"{cliente.get_absolute_url()}#bens"


class BemSeguradoDetailView(DetailView):
    """Todos os dados do veículo ou do imóvel, para consulta, com a apólice e o histórico."""

    model = BemSegurado
    template_name = "apolices/bem.html"

    def get_queryset(self):
        return BemSegurado.objects.select_related(
            "contrato__cliente", "contrato__seguradora", "contrato__ramo"
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempoDoBem(self.object).eventos()
        return contexto


class BlocosDoBemMixin:
    """O formulário em blocos, como a página do veículo ou do imóvel."""

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        form = contexto["form"]
        contexto["formularios"] = [
            (titulo, SecaoDoFormulario(form, campos, principal=indice == 0))
            for indice, (titulo, campos) in enumerate(form.blocos.items())
        ]
        return contexto


class BemSeguradoCreateView(BlocosDoBemMixin, FormularioMixin, CreateView):
    """Veículo ou imóvel de um contrato: o ramo do contrato diz qual dos dois."""

    model = BemSegurado

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(
            Contrato.objects.select_related("cliente", "seguradora", "ramo"),
            pk=kwargs["contrato_pk"],
        )
        self.tipo = self.contrato.ramo.bem_segurado
        if not self.tipo:
            raise Http404("O ramo deste contrato não guarda veículos nem imóveis.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return FORMULARIOS_DOS_BENS[self.tipo]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = BemSegurado(contrato=self.contrato, tipo=self.tipo)
        return kwargs

    def get_titulo(self) -> str:
        nome = TipoDeBem(self.tipo).label.lower()
        return f"Novo {nome} de {self.contrato.cliente} · {self.contrato}"

    def get_url_cancelar(self) -> str:
        return url_dos_bens(self.contrato.cliente)

    def form_valid(self, form):
        self.mensagem_sucesso = f"{TipoDeBem(self.tipo).label} cadastrado."
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return url_dos_bens(self.contrato.cliente)


class BemSeguradoUpdateView(BlocosDoBemMixin, FormularioMixin, UpdateView):
    model = BemSegurado

    def get_queryset(self):
        return BemSegurado.objects.select_related("contrato__cliente", "contrato__seguradora")

    def get_form_class(self):
        return FORMULARIOS_DOS_BENS[self.object.tipo]

    def get_titulo(self) -> str:
        return f"Editar {self.object.get_tipo_display().lower()} {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()

    def form_valid(self, form):
        self.mensagem_sucesso = f"{self.object.get_tipo_display()} atualizado."
        return super().form_valid(form)


class BemSeguradoDeleteView(ExclusaoConfirmadaView):
    model = BemSegurado
    permission_required = "apolices.delete_bemsegurado"

    def get_queryset(self):
        return BemSegurado.objects.select_related("contrato__cliente")

    def get_texto_esperado(self) -> str:
        return self.object.nome_para_confirmar

    def get_success_url(self) -> str:
        return url_dos_bens(self.object.contrato.cliente)
