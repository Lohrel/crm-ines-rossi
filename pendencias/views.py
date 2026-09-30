from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from apolices.models import Contrato
from clientes.forms import BuscaClienteForm
from clientes.models import Cliente, Unidade
from clientes.views import FormularioMixin, destino_seguro
from movimentacoes.models import Movimentacao
from pendencias.forms import FiltroPendenciasForm, PendenciaForm
from pendencias.historico import LinhaDoTempoDaPendencia
from pendencias.models import DIAS_DE_ANTECEDENCIA, Pendencia


class PendenciaListView(ListView):
    """Por padrão, as em aberto de todos, pelo prazo; filtros por responsável e situação."""

    template_name = "pendencias/lista.html"
    paginate_by = 100

    def get_queryset(self):
        self.filtro = FiltroPendenciasForm(self.request.GET or None)
        self.dados = self.filtro.cleaned_data if self.filtro.is_valid() else {}
        pendencias = Pendencia.objects.para_tabela()
        for campo in ("responsavel", "cliente", "contrato", "movimentacao"):
            if valor := self.dados.get(campo):
                pendencias = pendencias.filter(**{campo: valor})
        if termo := self.dados.get("q"):
            pendencias = pendencias.buscar(termo)
        # O resumo do topo conta as em aberto com os mesmos filtros.
        self.do_filtro = pendencias
        situacao = self.dados.get("situacao", "")
        if situacao == "":
            return pendencias.em_aberto()
        if situacao == FiltroPendenciasForm.ATENCAO:
            limite = date.today() + timedelta(days=DIAS_DE_ANTECEDENCIA)
            return pendencias.em_aberto().filter(prazo__lte=limite)
        if situacao == "concluidas":
            return pendencias.concluidas().order_by("-concluida_em", "-pk")
        return pendencias.order_by("-prazo", "-pk")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = date.today()
        em_aberto = self.do_filtro.em_aberto()
        contexto["resumo"] = {
            "em_aberto": em_aberto.count(),
            "vencidas": em_aberto.vencidas(hoje).count(),
            "vencendo": em_aberto.vencendo(hoje).count(),
        }
        contexto["dias_de_antecedencia"] = DIAS_DE_ANTECEDENCIA
        contexto["filtro"] = self.filtro
        # Vindo da movimentação, do contrato ou do cliente, a lista mostra só as deles, e a
        # nova pendência já sai ligada a eles.
        campo = next(
            (c for c in ("movimentacao", "contrato", "cliente") if self.dados.get(c)), None
        )
        if campo:
            contexto["ligacao"] = {"campo": campo, "registro": self.dados[campo]}
            parametros = {campo: self.dados[campo].pk, "proximo": self.request.get_full_path()}
            contexto["url_nova"] = f"{reverse('pendencias:nova')}?{urlencode(parametros)}"
        else:
            contexto["url_nova"] = reverse("pendencias:escolher_cliente")
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class EscolherClienteView(ListView):
    """Primeiro passo da nova pendência feita pela lista: de qual cliente é."""

    template_name = "pendencias/escolher_cliente.html"
    paginate_by = 25

    def get_queryset(self):
        self.busca = BuscaClienteForm(self.request.GET or None)
        clientes = Cliente.objects.prefetch_related("unidades")
        if self.busca.is_valid():
            clientes = clientes.buscar(self.busca.cleaned_data["q"])
            if tipo := self.busca.cleaned_data["tipo"]:
                clientes = clientes.filter(tipo=tipo)
        return clientes

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["busca"] = self.busca
        contexto["volta"] = urlencode({"proximo": reverse("pendencias:lista")})
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


def ligacoes_pedidas(parametros) -> dict | None:
    """Cliente da nova pendência e o que mais veio no link (unidade, contrato, movimentação).

    Vindo de uma movimentação, a pendência já fica com o cliente, a unidade e o
    plano da pessoa. Sem cliente, devolve None.
    """

    def buscar(consulta, nome: str):
        valor = parametros.get(nome, "")
        return get_object_or_404(consulta, pk=valor) if valor.isdigit() else None

    consulta = Movimentacao.objects.select_related("cliente", "beneficiario__titular", "contrato")
    if movimentacao := buscar(consulta, "movimentacao"):
        return {
            "cliente": movimentacao.cliente,
            "unidade": movimentacao.beneficiario.unidade_efetiva,
            "contrato": movimentacao.contrato,
            "movimentacao": movimentacao,
        }
    if contrato := buscar(Contrato.objects.select_related("cliente"), "contrato"):
        return {"cliente": contrato.cliente, "contrato": contrato}
    if unidade := buscar(Unidade.objects.select_related("cliente"), "unidade"):
        return {"cliente": unidade.cliente, "unidade": unidade}
    if cliente := buscar(Cliente.objects.all(), "cliente"):
        return {"cliente": cliente}
    return None


class PendenciaCreateView(FormularioMixin, CreateView):
    model = Pendencia
    form_class = PendenciaForm
    mensagem_sucesso = "Pendência registrada."

    def dispatch(self, request, *args, **kwargs):
        self.ligacoes = ligacoes_pedidas(request.GET)
        if self.ligacoes is None:
            return redirect("pendencias:escolher_cliente")
        self.cliente = self.ligacoes["cliente"]
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.cliente, "usuario": self.request.user}

    def get_initial(self):
        return {
            nome: registro.pk
            for nome, registro in self.ligacoes.items()
            if nome != "cliente" and registro is not None
        }

    def get_titulo(self) -> str:
        return f"Nova pendência de {self.cliente}"

    def get_url_cancelar(self) -> str:
        # Volta para onde a pendência foi pedida.
        if movimentacao := self.ligacoes.get("movimentacao"):
            padrao = movimentacao.get_absolute_url()
        elif contrato := self.ligacoes.get("contrato"):
            padrao = f"{reverse('pendencias:lista')}?contrato={contrato.pk}"
        else:
            padrao = self.cliente.get_absolute_url()
        return destino_seguro(self.request, padrao)

    def get_success_url(self) -> str:
        return self.get_url_cancelar()


class PendenciaDetailView(DetailView):
    model = Pendencia
    template_name = "pendencias/detalhe.html"

    def get_queryset(self):
        return Pendencia.objects.para_tabela().select_related("registrada_por")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempoDaPendencia(self.object).eventos()
        return contexto


class PendenciaUpdateView(FormularioMixin, UpdateView):
    model = Pendencia
    form_class = PendenciaForm
    mensagem_sucesso = "Pendência atualizada."

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.object.cliente}

    def get_titulo(self) -> str:
        return f"Editar pendência de {self.object.cliente}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class MudarSituacaoView(SingleObjectMixin, View):
    """Botões de concluir e reabrir: registram quem fez e voltam para a página de origem."""

    model = Pendencia
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        pendencia = self.get_object()
        try:
            texto = self.mudar(pendencia)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        else:
            messages.success(request, f"{texto}: {pendencia}.")
        return redirect(destino_seguro(request, pendencia.get_absolute_url()))

    def mudar(self, pendencia: Pendencia) -> str:
        raise NotImplementedError


class ConcluirView(MudarSituacaoView):
    def mudar(self, pendencia: Pendencia) -> str:
        pendencia.concluir(self.request.user)
        return "Pendência concluída"


class ReabrirView(MudarSituacaoView):
    def mudar(self, pendencia: Pendencia) -> str:
        pendencia.reabrir()
        return "Pendência reaberta"
