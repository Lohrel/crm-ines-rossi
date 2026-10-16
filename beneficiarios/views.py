from datetime import date
from io import BytesIO
from urllib.parse import urlencode

from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)
from django.views.generic.detail import SingleObjectMixin

from apolices.models import Contrato, Subfatura
from beneficiarios.forms import (
    AnexoForm,
    BuscaBeneficiarioForm,
    DependenteForm,
    EncerrarVinculoForm,
    EntradaDasVidasNovasForm,
    ImportacaoDeVidasForm,
    MesDaPlanilhaForm,
    SubfaturaForm,
    TitularForm,
    VinculoForm,
)
from beneficiarios.historico import LinhaDoTempoDoBeneficiario
from beneficiarios.importacao_de_vidas import (
    ImportacaoDeVidas,
    PlanilhaLida,
    desempacotar,
    empacotar,
)
from beneficiarios.models import Anexo, Beneficiario, Vinculo
from beneficiarios.seguro_de_vida import TIPO_XLSX, PlanilhaDoSeguroDeVida, mes_sugerido
from beneficiarios.vidas import VidasDoCliente, filtro_de_ativos
from clientes.models import Cliente
from clientes.views import ExclusaoConfirmadaView, FormularioMixin, entregar_arquivo


class BeneficiarioListView(ListView):
    """Titulares de um cliente com seus dependentes, e o quadro de vidas."""

    template_name = "beneficiarios/lista.html"
    paginate_by = 50

    def get_cliente(self) -> Cliente:
        if not hasattr(self, "cliente"):
            self.cliente = get_object_or_404(Cliente, pk=self.kwargs["cliente_pk"])
        return self.cliente

    def get_queryset(self):
        cliente = self.get_cliente()
        self.busca = BuscaBeneficiarioForm(self.request.GET or None, cliente=cliente)
        pessoas = cliente.beneficiarios.all()
        filtros = self.busca.cleaned_data if self.busca.is_valid() else {}
        if not filtros.get("inativos"):
            pessoas = pessoas.filter(filtro_de_ativos())
        if contrato := filtros.get("contrato"):
            pessoas = pessoas.filter(vinculos__contrato=contrato)
        if unidade := filtros.get("unidade"):
            pessoas = pessoas.filter(unidade=unidade) | pessoas.filter(titular__unidade=unidade)
        if termo := filtros.get("q"):
            pessoas = pessoas.buscar(termo)
        # A lista mostra os titulares; quem casa com o filtro sendo dependente traz o titular.
        encontrados = pessoas.values("pk")
        titulares = cliente.beneficiarios.titulares().filter(
            pk__in=encontrados
        ) | cliente.beneficiarios.titulares().filter(dependentes__in=encontrados)
        planos = Prefetch(
            "vinculos",
            queryset=Vinculo.objects.ativos().select_related("contrato__ramo"),
            to_attr="planos",
        )
        return (
            titulares.distinct()
            .select_related("unidade")
            .prefetch_related(
                planos,
                Prefetch("dependentes", queryset=Beneficiario.objects.prefetch_related(planos)),
            )
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        cliente = self.get_cliente()
        contratos = list(cliente.contratos.de_pessoas().select_related("ramo", "seguradora"))
        vidas = VidasDoCliente(cliente)
        contexto.update(
            cliente=cliente,
            busca=self.busca,
            contratos=contratos,
            vidas=vidas,
            quadro=vidas.quadro(contratos, cliente.unidades.all()),
            total_por_contrato=[vidas.por_contrato.get(c.pk, 0) for c in contratos],
        )
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class BeneficiarioDetailView(DetailView):
    model = Beneficiario
    template_name = "beneficiarios/detalhe.html"

    def get_queryset(self):
        return Beneficiario.objects.select_related("cliente", "titular", "unidade")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        pessoa = self.object
        contexto["planos"] = planos = list(
            pessoa.vinculos.select_related("contrato__seguradora", "contrato__ramo")
        )
        # "Alterar plano" só aparece quando há outro plano vigente do mesmo ramo.
        vigentes = Contrato.objects.vigentes().filter(cliente=pessoa.cliente)
        vigentes = list(vigentes.values_list("pk", "ramo_id"))
        for plano in planos:
            plano.pode_alterar = (
                pessoa.eh_titular
                and plano.data_exclusao is None
                and any(r == plano.contrato.ramo_id and c != plano.contrato_id for c, r in vigentes)
            )
        contexto["dependentes"] = pessoa.dependentes.prefetch_related(
            Prefetch(
                "vinculos",
                queryset=Vinculo.objects.ativos().select_related("contrato__ramo"),
                to_attr="planos",
            )
        )
        contexto["anexos"] = pessoa.anexos.select_related("enviado_por")
        contexto["movimentacoes"] = pessoa.movimentacoes.select_related(
            "contrato__ramo", "contrato_anterior"
        ).order_by("-recebida_em")
        contexto["historico"] = LinhaDoTempoDoBeneficiario(pessoa).eventos()
        return contexto


class TitularCreateView(FormularioMixin, CreateView):
    model = Beneficiario
    form_class = TitularForm
    mensagem_sucesso = "Titular cadastrado. Agora inclua os planos."

    def get_cliente(self) -> Cliente:
        return get_object_or_404(Cliente, pk=self.kwargs["cliente_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.get_cliente()}

    def get_initial(self):
        unidade = self.request.GET.get("unidade", "")
        return {"unidade": unidade} if unidade.isdigit() else {}

    def get_titulo(self) -> str:
        return f"Novo titular de {self.get_cliente()}"

    def get_url_cancelar(self) -> str:
        return self.get_cliente().get_absolute_url()


class DependenteCreateView(FormularioMixin, CreateView):
    model = Beneficiario
    form_class = DependenteForm
    mensagem_sucesso = "Dependente cadastrado. Agora escolha os planos dele."

    def get_titular(self) -> Beneficiario:
        return get_object_or_404(Beneficiario.objects.titulares(), pk=self.kwargs["titular_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "titular": self.get_titular()}

    def get_titulo(self) -> str:
        return f"Novo dependente de {self.get_titular()}"

    def get_url_cancelar(self) -> str:
        return self.get_titular().get_absolute_url()


class BeneficiarioUpdateView(FormularioMixin, UpdateView):
    model = Beneficiario
    mensagem_sucesso = "Dados atualizados."

    def get_form_class(self):
        return TitularForm if self.object.eh_titular else DependenteForm

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class BeneficiarioDeleteView(ExclusaoConfirmadaView):
    model = Beneficiario
    permission_required = "beneficiarios.delete_beneficiario"
    aviso = (
        "Serão excluídos também os planos e os arquivos anexados desta pessoa. "
        "Para registrar que ela saiu de um plano, use a exclusão do plano, não esta tela."
    )

    def get_success_url(self) -> str:
        return self.object.cliente.get_absolute_url()


class VinculoCreateView(FormularioMixin, CreateView):
    model = Vinculo
    form_class = VinculoForm
    mensagem_sucesso = "Inclusão no plano registrada."

    def get_beneficiario(self) -> Beneficiario:
        return get_object_or_404(Beneficiario, pk=self.kwargs["beneficiario_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "beneficiario": self.get_beneficiario()}

    @transaction.atomic
    def form_valid(self, form):
        return super().form_valid(form)

    def get_titulo(self) -> str:
        return f"Incluir {self.get_beneficiario()} num plano"

    def get_url_cancelar(self) -> str:
        return self.get_beneficiario().get_absolute_url()


class VinculoUpdateView(FormularioMixin, UpdateView):
    model = Vinculo
    form_class = VinculoForm
    mensagem_sucesso = "Plano atualizado."

    def get_titulo(self) -> str:
        return f"Editar plano de {self.object.beneficiario}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class VinculoEncerrarView(FormularioMixin, SingleObjectMixin, FormView):
    """Exclusão do plano: registra a data; do titular, leva junto os dependentes."""

    model = Vinculo
    form_class = EncerrarVinculoForm

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "vinculo": self.object}

    def get_titulo(self) -> str:
        return f"Excluir {self.object.beneficiario} do plano {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        if self.object.beneficiario.eh_titular:
            contexto["aviso"] = "Os dependentes que estão neste plano também serão excluídos dele."
        return contexto

    def form_valid(self, form):
        encerrados = self.object.encerrar(form.cleaned_data["data_exclusao"])
        texto = "Exclusão do plano registrada"
        if len(encerrados) > 1:
            texto += f" (com {len(encerrados) - 1} dependente(s))"
        messages.success(self.request, texto + ".")
        return redirect(self.object.get_absolute_url())


class AnexoCreateView(FormularioMixin, CreateView):
    model = Anexo
    form_class = AnexoForm
    mensagem_sucesso = "Arquivo anexado."

    def get_beneficiario(self) -> Beneficiario:
        return get_object_or_404(Beneficiario, pk=self.kwargs["beneficiario_pk"])

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "beneficiario": self.get_beneficiario(),
            "usuario": self.request.user,
        }

    def get_titulo(self) -> str:
        return f"Anexar arquivo de {self.get_beneficiario()}"

    def get_url_cancelar(self) -> str:
        return self.get_beneficiario().get_absolute_url()


def baixar_anexo(request, pk: int):
    """Entrega o arquivo só para quem está logado (o login é exigido pelo middleware)."""
    return entregar_arquivo(request, get_object_or_404(Anexo, pk=pk))


class AnexoDeleteView(ExclusaoConfirmadaView):
    model = Anexo
    permission_required = "beneficiarios.delete_anexo"
    aviso = "O arquivo será apagado do servidor."

    def get_texto_esperado(self) -> str:
        return self.object.nome_original

    def get_success_url(self) -> str:
        return self.object.get_absolute_url()


class SeguroDeVidaView(TemplateView):
    """Planilha do seguro de vida de um contrato: resumo do mês, download e subfaturas."""

    template_name = "beneficiarios/seguro_de_vida.html"

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(
            Contrato.objects.select_related("cliente", "seguradora", "ramo"),
            pk=kwargs["contrato_pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        planilha = self._planilha(request.GET)
        if planilha and "baixar" in request.GET:
            resposta = FileResponse(
                BytesIO(planilha.gerar()),
                as_attachment=True,
                filename=planilha.nome_do_arquivo,
                content_type=TIPO_XLSX,
            )
            resposta["Cache-Control"] = "private, no-store"
            return resposta
        return self._mostrar(planilha, self._subfaturas())

    def post(self, request, *args, **kwargs):
        """Salva Local, subfatura e boleto separado das filiais."""
        subfaturas = self._subfaturas(request.POST)
        planilha = self._planilha(request.POST)
        if all(form.is_valid() for _, form in subfaturas):
            with transaction.atomic():
                for _, form in subfaturas:
                    if form.instance.pk or form.has_changed():
                        form.save()
            messages.success(request, "Subfaturas salvas.")
            url = reverse("beneficiarios:seguro_de_vida", args=[self.contrato.pk])
            if planilha:
                url += "?" + urlencode({"mes": f"{planilha.data:%m/%Y}"})
            return redirect(url)
        return self._mostrar(planilha, subfaturas)

    def _planilha(self, dados) -> PlanilhaDoSeguroDeVida | None:
        """A planilha do mês pedido (ou do sugerido); nenhuma sem capital no contrato."""
        sugerido = mes_sugerido(date.today())
        pedido = dados if dados.get("mes") else None
        self.form = MesDaPlanilhaForm(pedido, initial={"mes": sugerido})
        if self.form.is_bound and not self.form.is_valid():
            return None
        if not self.contrato.calcula_capital:
            return None
        mes = self.form.cleaned_data["mes"] if self.form.is_bound else sugerido
        return PlanilhaDoSeguroDeVida(self.contrato, mes)

    def _mostrar(self, planilha, subfaturas):
        return self.render_to_response(
            self.get_context_data(planilha=planilha, subfaturas=subfaturas)
        )

    def _subfaturas(self, dados=None) -> list[tuple]:
        """Um formulário por filial coberta pelo contrato (ou por todas, se não indicar)."""
        cliente = self.contrato.cliente
        if not cliente.eh_empresa:
            return []
        unidades = list(self.contrato.unidades.all()) or list(cliente.unidades.all())
        existentes = self.contrato.subfaturas_por_unidade()
        return [
            (
                unidade,
                SubfaturaForm(
                    dados,
                    filial=unidade,
                    prefix=f"unidade-{unidade.pk}",
                    instance=existentes.get(unidade.pk)
                    or Subfatura(contrato=self.contrato, unidade=unidade),
                ),
            )
            for unidade in unidades
        ]

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "contrato": self.contrato, "form": self.form}


class ImportarVidasView(TemplateView):
    """Lê a planilha atual do seguro de vida, mostra a prévia de cada vida e importa."""

    template_name = "beneficiarios/importar_vidas.html"

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(
            Contrato.objects.select_related("cliente", "seguradora", "ramo"),
            pk=kwargs["contrato_pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self._mostrar(form=ImportacaoDeVidasForm())

    def post(self, request, *args, **kwargs):
        if not self.contrato.calcula_capital:
            return redirect("beneficiarios:importar_vidas", self.contrato.pk)
        if "dados" not in request.POST:
            return self._ler_arquivo()
        try:
            contrato, planilha = desempacotar(request.POST["dados"])
        except signing.BadSignature:
            messages.error(request, "A prévia expirou. Envie a planilha de novo.")
            return redirect("beneficiarios:importar_vidas", self.contrato.pk)
        if contrato != self.contrato.pk:
            raise Http404
        entrada = EntradaDasVidasNovasForm(request.POST)
        data = entrada.cleaned_data["entrada"] if entrada.is_valid() else self._sugerida(planilha)
        importacao = ImportacaoDeVidas(self.contrato, planilha, data, self._filiais_escolhidas())
        if request.POST.get("acao") != "confirmar" or not entrada.is_valid():
            return self._mostrar(planilha, importacao.previa(), entrada, data)
        relatorio = importacao.gravar()
        if not relatorio.gravado:
            messages.warning(request, "Escolha a filial das pessoas novas antes de confirmar.")
        return self._mostrar(planilha, relatorio, entrada, data, concluida=relatorio.gravado)

    def _ler_arquivo(self):
        form = ImportacaoDeVidasForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self._mostrar(form=form)
        planilha = form.planilha
        data = self._sugerida(planilha)
        relatorio = ImportacaoDeVidas(self.contrato, planilha, data).previa()
        entrada = EntradaDasVidasNovasForm(initial={"entrada": data})
        return self._mostrar(planilha, relatorio, entrada, data)

    @staticmethod
    def _sugerida(planilha: PlanilhaLida) -> date:
        """A data da planilha (no nome da aba) ou, sem ela, o dia 1º do mês corrente."""
        return planilha.data or date.today().replace(day=1)

    def _filiais_escolhidas(self) -> dict[str, int]:
        """A filial escolhida na prévia para cada subfatura (campo filial-<SUB>)."""
        return {
            nome.removeprefix("filial-"): int(valor)
            for nome, valor in self.request.POST.items()
            if nome.startswith("filial-") and valor.isdigit()
        }

    def _mostrar(
        self, planilha=None, relatorio=None, entrada=None, data=None, form=None, concluida=False
    ):
        contexto = {
            "contrato": self.contrato,
            "form": form,
            "planilha": planilha,
            "relatorio": relatorio,
            "entrada": entrada,
            "data": data,
            "concluida": concluida,
        }
        if relatorio and not concluida:
            contexto["dados"] = empacotar(self.contrato, planilha)
        return self.render_to_response(self.get_context_data(**contexto))
