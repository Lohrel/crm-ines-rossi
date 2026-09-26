from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from clientes.forms import (
    BuscaClienteForm,
    ContatoForm,
    EmpresaForm,
    PessoaFisicaForm,
    UnidadeForm,
)
from clientes.historico import LinhaDoTempo
from clientes.models import Cliente, Contato, Unidade


class ClienteListView(ListView):
    model = Cliente
    paginate_by = 25
    template_name = "clientes/lista.html"

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
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class ClienteDetailView(DetailView):
    model = Cliente
    template_name = "clientes/detalhe.html"

    def get_queryset(self):
        return Cliente.objects.prefetch_related(
            Prefetch("unidades", queryset=Unidade.objects.prefetch_related("contatos"))
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempo(self.object).eventos()
        contexto["contratos"] = self.object.contratos.select_related(
            "seguradora", "ramo"
        ).prefetch_related("unidades")
        return contexto


class FormularioMixin:
    """Título, mensagem de sucesso e página de retorno comuns aos formulários."""

    template_name = "clientes/formulario.html"
    titulo = ""
    mensagem_sucesso = "Salvo com sucesso."

    def get_titulo(self) -> str:
        return self.titulo

    def get_url_cancelar(self) -> str:
        return reverse("clientes:lista")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = self.get_titulo()
        contexto["url_cancelar"] = self.get_url_cancelar()
        contexto["formularios"] = [("", contexto["form"])]
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, self.mensagem_sucesso)
        return resposta


class PessoaFisicaCreateView(FormularioMixin, CreateView):
    form_class = PessoaFisicaForm
    titulo = "Nova pessoa física"
    mensagem_sucesso = "Cliente cadastrado."


class EmpresaCreateView(View):
    """Cadastra a empresa junto com a primeira unidade (matriz)."""

    template_name = "clientes/formulario.html"

    def get(self, request):
        return self._renderizar(EmpresaForm(), self._unidade_form())

    def post(self, request):
        empresa_form = EmpresaForm(request.POST)
        unidade_form = self._unidade_form(request.POST)
        if empresa_form.is_valid() and unidade_form.is_valid():
            with transaction.atomic():
                empresa = empresa_form.save()
                unidade = unidade_form.save(commit=False)
                unidade.cliente = empresa
                unidade.save()
            messages.success(request, "Empresa cadastrada. Adicione as filiais e os contatos.")
            return redirect(empresa)
        return self._renderizar(empresa_form, unidade_form)

    @staticmethod
    def _unidade_form(dados=None) -> UnidadeForm:
        return UnidadeForm(dados, prefix="unidade", initial={"matriz": True})

    def _renderizar(self, empresa_form, unidade_form):
        return render(
            self.request,
            self.template_name,
            {
                "titulo": "Nova empresa",
                "formularios": [
                    ("Empresa", empresa_form),
                    ("Primeira unidade (matriz)", unidade_form),
                ],
                "url_cancelar": reverse("clientes:lista"),
            },
        )


class ClienteUpdateView(FormularioMixin, UpdateView):
    model = Cliente
    mensagem_sucesso = "Cliente atualizado."

    def get_form_class(self):
        return EmpresaForm if self.object.eh_empresa else PessoaFisicaForm

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class UnidadeFormMixin(FormularioMixin):
    model = Unidade
    form_class = UnidadeForm

    def get_url_cancelar(self) -> str:
        return self.get_cliente().get_absolute_url()


class UnidadeCreateView(UnidadeFormMixin, CreateView):
    mensagem_sucesso = "Unidade cadastrada."

    def get_cliente(self) -> Cliente:
        return get_object_or_404(Cliente.objects.empresas(), pk=self.kwargs["cliente_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.get_cliente()}

    def get_titulo(self) -> str:
        return f"Nova unidade de {self.get_cliente()}"


class UnidadeUpdateView(UnidadeFormMixin, UpdateView):
    mensagem_sucesso = "Unidade atualizada."

    def get_cliente(self) -> Cliente:
        return self.object.cliente

    def get_titulo(self) -> str:
        return f"Editar unidade {self.object}"


class ContatoFormMixin(FormularioMixin):
    model = Contato
    form_class = ContatoForm

    def get_url_cancelar(self) -> str:
        return self.get_unidade().get_absolute_url()


class ContatoCreateView(ContatoFormMixin, CreateView):
    mensagem_sucesso = "Contato cadastrado."

    def get_unidade(self) -> Unidade:
        return get_object_or_404(Unidade, pk=self.kwargs["unidade_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "unidade": self.get_unidade()}

    def get_titulo(self) -> str:
        return f"Novo contato em {self.get_unidade()}"


class ContatoUpdateView(ContatoFormMixin, UpdateView):
    mensagem_sucesso = "Contato atualizado."

    def get_unidade(self) -> Unidade:
        return self.object.unidade

    def get_titulo(self) -> str:
        return f"Editar contato {self.object}"


class ContatoDeleteView(DeleteView):
    model = Contato
    template_name = "clientes/confirmar_exclusao.html"

    def get_success_url(self) -> str:
        return self.object.unidade.get_absolute_url()

    def form_valid(self, form):
        messages.success(self.request, f"Contato {self.object} removido.")
        return super().form_valid(form)
