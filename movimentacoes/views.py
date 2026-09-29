from datetime import date
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from beneficiarios.models import Beneficiario, Vinculo
from clientes.views import FormularioMixin
from movimentacoes.forms import (
    EdicaoMovimentacaoForm,
    FiltroMovimentacoesForm,
    MovimentacaoForm,
    PlanilhaForm,
    formulario_da_etapa,
)
from movimentacoes.historico import LinhaDoTempoDaMovimentacao
from movimentacoes.models import Etapa, Movimentacao
from movimentacoes.planilha import TIPO_XLSX, PlanilhaDoMes

TIPOS_NA_URL = {
    "inclusao": Movimentacao.Tipo.INCLUSAO,
    "exclusao": Movimentacao.Tipo.EXCLUSAO,
    "alteracao": Movimentacao.Tipo.ALTERACAO,
}
AVISOS_DO_TITULAR = {
    Movimentacao.Tipo.EXCLUSAO: (
        "Ao aprovar a exclusão do titular, os dependentes deste plano saem junto."
    ),
    Movimentacao.Tipo.ALTERACAO: (
        "Ao aprovar a alteração do titular, os dependentes do plano atual mudam junto "
        "para o novo plano."
    ),
}


def aviso_dos_dependentes(tipo: str, pessoa: Beneficiario, plano_de_saida=None) -> str:
    """Na exclusão e na alteração do titular, avisa que os dependentes do plano vão junto."""
    if tipo not in AVISOS_DO_TITULAR or not pessoa.eh_titular:
        return ""
    dependentes = Vinculo.objects.filter(beneficiario__titular=pessoa, data_exclusao__isnull=True)
    if plano_de_saida:
        dependentes = dependentes.filter(contrato=plano_de_saida)
    return AVISOS_DO_TITULAR[tipo] if dependentes.exists() else ""


class MovimentacaoListView(ListView):
    """Em aberto (de qualquer mês) por padrão; filtros por mês da vigência, cliente e tipo."""

    template_name = "movimentacoes/lista.html"
    paginate_by = 100

    def get_queryset(self):
        self.filtro = FiltroMovimentacoesForm(self.request.GET or None)
        movimentacoes = Movimentacao.objects.select_related(
            "cliente",
            "beneficiario__titular",
            "beneficiario__unidade",
            "contrato__ramo",
            "contrato__seguradora",
            "contrato_anterior",
            "solicitante",
        )
        dados = self.filtro.cleaned_data if self.filtro.is_valid() else {}
        situacao = dados.get("situacao", "")
        if situacao == "":
            movimentacoes = movimentacoes.em_aberto()
        elif situacao != "todas":
            movimentacoes = movimentacoes.filter(etapa=situacao)
        if mes := dados.get("mes"):
            movimentacoes = movimentacoes.com_vigencia_no_mes(mes.year, mes.month)
        if cliente := dados.get("cliente"):
            movimentacoes = movimentacoes.filter(cliente=cliente)
        if tipo := dados.get("tipo"):
            movimentacoes = movimentacoes.filter(tipo=tipo)
        if termo := dados.get("q"):
            movimentacoes = movimentacoes.buscar(termo)
        return movimentacoes

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["filtro"] = self.filtro
        contexto["total_em_aberto"] = Movimentacao.objects.em_aberto().count()
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class MovimentacaoDetailView(DetailView):
    model = Movimentacao
    template_name = "movimentacoes/detalhe.html"

    def get_queryset(self):
        return Movimentacao.objects.select_related(
            "cliente",
            "beneficiario__titular",
            "contrato__ramo",
            "contrato__seguradora",
            "contrato_anterior__ramo",
            "contrato_anterior__seguradora",
            "origem",
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["proximas"] = [Etapa(e) for e in self.object.proximas_etapas]
        contexto["refeitas"] = self.object.refeitas.all()
        # As em aberto primeiro; depois as concluídas, da mais recente.
        contexto["pendencias"] = self.object.pendencias.para_tabela().order_by(
            F("concluida_em").desc(nulls_first=True), "prazo"
        )
        contexto["historico"] = LinhaDoTempoDaMovimentacao(self.object).eventos()
        return contexto


class MovimentacaoCreateView(FormularioMixin, CreateView):
    model = Movimentacao
    form_class = MovimentacaoForm

    def dispatch(self, request, *args, **kwargs):
        if kwargs["tipo"] not in TIPOS_NA_URL:
            raise Http404
        self.tipo = TIPOS_NA_URL[kwargs["tipo"]]
        self.beneficiario = get_object_or_404(
            Beneficiario.objects.select_related("cliente", "titular"), pk=kwargs["beneficiario_pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "tipo": self.tipo,
            "beneficiario": self.beneficiario,
            "usuario": self.request.user,
        }

    def plano_do_botao(self) -> int | None:
        """O plano da linha em que se clicou (Solicitar exclusão, Alterar plano)."""
        contrato = self.request.GET.get("contrato", "")
        return int(contrato) if contrato.isdigit() else None

    def get_initial(self):
        plano = self.plano_do_botao()
        if plano is None:
            return {}
        # Na alteração, o plano do botão é o atual, de onde a pessoa sai.
        campo = "contrato_anterior" if self.tipo == Movimentacao.Tipo.ALTERACAO else "contrato"
        return {campo: plano}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["aviso"] = aviso_dos_dependentes(
            self.tipo, self.beneficiario, self.plano_do_botao()
        )
        return contexto

    @transaction.atomic
    def form_valid(self, form):
        return super().form_valid(form)

    @property
    def mensagem_sucesso(self) -> str:
        return f"{Movimentacao.Tipo(self.tipo).label} registrada."

    def get_titulo(self) -> str:
        return f"{Movimentacao.Tipo(self.tipo).label} de {self.beneficiario}"

    def get_url_cancelar(self) -> str:
        return self.beneficiario.get_absolute_url()


class MovimentacaoUpdateView(FormularioMixin, UpdateView):
    model = Movimentacao
    form_class = EdicaoMovimentacaoForm
    mensagem_sucesso = "Movimentação atualizada."

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class MudarEtapaView(FormularioMixin, UpdateView):
    """Leva o pedido para a próxima etapa, pedindo só os dados daquela etapa."""

    model = Movimentacao

    def dispatch(self, request, *args, **kwargs):
        try:
            self.etapa = Etapa(kwargs["etapa"])
        except ValueError as erro:
            raise Http404 from erro
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        movimentacao = super().get_object(queryset)
        if self.etapa not in movimentacao.proximas_etapas:
            raise Http404
        return movimentacao

    def get_form_class(self):
        return formulario_da_etapa(self.etapa)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        mov = self.object
        if self.etapa == Etapa.APROVADA:
            contexto["aviso"] = aviso_dos_dependentes(
                mov.tipo, mov.beneficiario, mov.plano_de_saida_id
            )
        return contexto

    def form_valid(self, form):
        try:
            form.save()
        except ValidationError:
            return self.form_invalid(form)
        messages.success(self.request, f"Etapa alterada para {self.etapa.label}.")
        return redirect(self.object.get_absolute_url())

    def get_titulo(self) -> str:
        return f"{self.etapa.label}: {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class RefazerView(SingleObjectMixin, View):
    """Cria uma nova movimentação a partir de uma rejeitada."""

    model = Movimentacao

    def post(self, request, *args, **kwargs):
        rejeitada = self.get_object()
        try:
            nova = rejeitada.refazer(request.user)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return redirect(rejeitada.get_absolute_url())
        messages.success(request, "Nova movimentação criada a partir da rejeitada.")
        return redirect(nova.get_absolute_url())


class PlanilhaView(TemplateView):
    """Baixa a planilha de controle das inclusões de uma empresa, em Excel."""

    template_name = "movimentacoes/planilha.html"

    def get(self, request, *args, **kwargs):
        self.form = PlanilhaForm(request.GET or None, initial={"mes": date.today()})
        if not self.form.is_valid():
            return super().get(request, *args, **kwargs)
        planilha = PlanilhaDoMes(self.form.cleaned_data["cliente"], self.form.cleaned_data["mes"])
        resposta = FileResponse(
            BytesIO(planilha.gerar()),
            as_attachment=True,
            filename=planilha.nome_do_arquivo,
            content_type=TIPO_XLSX,
        )
        resposta["Cache-Control"] = "private, no-store"
        return resposta

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "form": self.form}
