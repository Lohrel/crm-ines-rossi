from datetime import date, timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apolices.forms import (
    ContratoForm,
    DocumentoDaSeguradoraForm,
    FiltroContratosForm,
    ImovelForm,
    SeguradoraForm,
    VeiculoForm,
)
from apolices.historico import LinhaDoTempoDaSeguradora, LinhaDoTempoDoBem
from apolices.models import (
    DIAS_PARA_RENOVACAO,
    BemSegurado,
    Contrato,
    DocumentoDaSeguradora,
    Seguradora,
    TipoDeBem,
    limpar_placa,
)
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
                "bens"
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
    return entregar_arquivo(get_object_or_404(DocumentoDaSeguradora, pk=pk))


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
