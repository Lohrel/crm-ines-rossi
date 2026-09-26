from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from beneficiarios.models import Beneficiario
from clientes.views import FormularioMixin
from movimentacoes.forms import (
    EdicaoMovimentacaoForm,
    FiltroMovimentacoesForm,
    MovimentacaoForm,
    formulario_da_etapa,
)
from movimentacoes.historico import LinhaDoTempoDaMovimentacao
from movimentacoes.models import Etapa, Movimentacao

TIPOS_NA_URL = {"inclusao": Movimentacao.Tipo.INCLUSAO, "exclusao": Movimentacao.Tipo.EXCLUSAO}


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
            "solicitante",
        )
        dados = self.filtro.cleaned_data if self.filtro.is_valid() else {}
        situacao = dados.get("situacao", "")
        if situacao == "":
            movimentacoes = movimentacoes.em_aberto()
        elif situacao != "todas":
            movimentacoes = movimentacoes.filter(etapa=situacao)
        if mes := dados.get("mes"):
            movimentacoes = movimentacoes.com_vigencia_no_mes(*mes)
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
            "cliente", "beneficiario__titular", "contrato__ramo", "contrato__seguradora", "origem"
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["proximas"] = [Etapa(e) for e in self.object.proximas_etapas]
        contexto["refeitas"] = self.object.refeitas.all()
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

    def get_initial(self):
        contrato = self.request.GET.get("contrato", "")
        return {"contrato": contrato} if contrato.isdigit() else {}

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
