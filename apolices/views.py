from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView

from apolices.forms import ContratoForm, FiltroContratosForm, SeguradoraForm
from apolices.models import Contrato, Seguradora
from clientes.models import Cliente
from clientes.views import FormularioMixin


class ContratoListView(ListView):
    """Todos os contratos, com filtros por seguradora, ramo, situação e vencimento."""

    model = Contrato
    paginate_by = 50
    template_name = "apolices/contratos.html"

    def get_queryset(self):
        self.filtro = FiltroContratosForm(self.request.GET or None)
        contratos = Contrato.objects.select_related("cliente", "seguradora", "ramo")
        if not self.filtro.is_valid():
            return contratos.vigentes()
        dados = self.filtro.cleaned_data
        situacao = dados["situacao"]
        if situacao == "":
            contratos = contratos.vigentes()
        elif situacao != "todas":
            contratos = contratos.filter(situacao=situacao)
        if termo := dados["q"].strip():
            contratos = contratos.filter(
                Q(numero__icontains=termo)
                | Q(produto__icontains=termo)
                | Q(cliente__nome__icontains=termo)
            )
        if dados["seguradora"]:
            contratos = contratos.filter(seguradora=dados["seguradora"])
        if dados["ramo"]:
            contratos = contratos.filter(ramo=dados["ramo"])
        if dados["boleto"]:
            contratos = contratos.com_boleto_da_corretora()
        if dados["vencimento"]:
            contratos = contratos.filter(dia_vencimento=dados["vencimento"])
        return contratos

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["filtro"] = self.filtro
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class ContratoCreateView(FormularioMixin, CreateView):
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


class ContratoUpdateView(FormularioMixin, UpdateView):
    model = Contrato
    form_class = ContratoForm
    mensagem_sucesso = "Contrato atualizado."

    def get_titulo(self) -> str:
        return f"Editar contrato {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class SeguradoraListView(ListView):
    model = Seguradora
    template_name = "apolices/seguradoras.html"


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
        return reverse("apolices:seguradoras")
