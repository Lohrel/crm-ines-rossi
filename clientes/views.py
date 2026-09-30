from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from beneficiarios.vidas import VidasDoCliente, anotar_vidas
from clientes.forms import (
    BuscaClienteForm,
    ConfirmacaoExclusaoForm,
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
            Prefetch("unidades", queryset=Unidade.objects.prefetch_related("contatos")),
            Prefetch("contatos", queryset=Contato.objects.prefetch_related("unidades")),
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempo(self.object).eventos()
        contexto["pendencias"] = self.object.pendencias.em_aberto().para_tabela()
        contratos = self.object.contratos.select_related("seguradora", "ramo")
        contratos = list(anotar_vidas(contratos.prefetch_related("unidades", "bens")))
        contexto["contratos"] = contratos
        # Auto e imóvel: os veículos e imóveis de cada apólice, para consulta.
        contexto["contratos_com_bens"] = [
            contrato for contrato in contratos if contrato.ramo.bem_segurado or contrato.bens.all()
        ]
        contexto["total_de_bens"] = sum(len(contrato.bens.all()) for contrato in contratos)
        vidas = VidasDoCliente(self.object)
        contexto["vidas"] = vidas
        for unidade in self.object.unidades.all():
            unidade.vidas = vidas.da_unidade(unidade.pk)
        return contexto


def destino_seguro(request, padrao: str) -> str:
    """A página de volta enviada em "proximo", se for deste sistema; senão, a padrão."""
    proximo = request.POST.get("proximo") or request.GET.get("proximo", "")
    seguro = url_has_allowed_host_and_scheme(
        proximo, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return proximo if seguro else padrao


class FormularioMixin:
    """Título, mensagem de sucesso e página de retorno comuns aos formulários."""

    template_name = "clientes/formulario.html"
    titulo = ""
    mensagem_sucesso = "Salvo com sucesso."
    texto_do_botao = "Salvar"

    def get_titulo(self) -> str:
        return self.titulo

    def get_url_cancelar(self) -> str:
        return reverse("clientes:lista")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = self.get_titulo()
        contexto["url_cancelar"] = self.get_url_cancelar()
        contexto["texto_do_botao"] = self.texto_do_botao
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
        return self.get_cliente().get_absolute_url()


class ContatoCreateView(ContatoFormMixin, CreateView):
    mensagem_sucesso = "Contato cadastrado."

    def get_cliente(self) -> Cliente:
        return get_object_or_404(Cliente.objects.empresas(), pk=self.kwargs["cliente_pk"])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "cliente": self.get_cliente()}

    def get_initial(self):
        # Vindo do botão de uma unidade, ela já aparece marcada.
        unidade = self.request.GET.get("unidade", "")
        return {"unidades": [unidade]} if unidade.isdigit() else {}

    def get_titulo(self) -> str:
        return f"Novo contato de {self.get_cliente()}"


class ContatoUpdateView(ContatoFormMixin, UpdateView):
    mensagem_sucesso = "Contato atualizado."

    def get_cliente(self) -> Cliente:
        return self.object.cliente

    def get_titulo(self) -> str:
        return f"Editar contato {self.object}"


class ContatoDeleteView(DeleteView):
    model = Contato
    template_name = "clientes/confirmar_exclusao.html"

    def get_success_url(self) -> str:
        return self.object.cliente.get_absolute_url()

    def form_valid(self, form):
        messages.success(self.request, f"Contato {self.object} removido.")
        return super().form_valid(form)


class ExclusaoConfirmadaView(PermissionRequiredMixin, SingleObjectMixin, FormView):
    """Exclusão que exige digitar o nome do registro e respeita os bloqueios do modelo."""

    template_name = "clientes/excluir.html"
    form_class = ConfirmacaoExclusaoForm
    raise_exception = True
    aviso = ""

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def get_texto_esperado(self) -> str:
        return str(self.object)

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()

    def get_aviso(self) -> str:
        """O que sai junto com o registro, mostrado antes da confirmação."""
        return self.aviso

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "texto_esperado": self.get_texto_esperado()}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["bloqueios"] = self.object.bloqueios_para_excluir()
        contexto["texto_esperado"] = self.get_texto_esperado()
        contexto["url_cancelar"] = self.get_url_cancelar()
        contexto["aviso"] = self.get_aviso()
        return contexto

    def form_valid(self, form):
        descricao = str(self.object)
        destino = self.get_success_url()
        try:
            self.object.excluir()
        except ValidationError as erro:
            form.add_error(None, erro)
            return self.form_invalid(form)
        messages.success(self.request, f"{descricao} foi excluído(a).")
        return redirect(destino)


def pendencias_que_saem_junto(registro: Cliente | Unidade, de: str) -> str:
    quantas = registro.pendencias.count()
    if quantas == 1:
        return f"A pendência {de} também será excluída."
    return f"As {quantas} pendências {de} também serão excluídas." if quantas else ""


class ClienteDeleteView(ExclusaoConfirmadaView):
    model = Cliente
    permission_required = "clientes.delete_cliente"

    def get_aviso(self) -> str:
        avisos = [pendencias_que_saem_junto(self.object, "deste cliente")]
        if self.object.eh_empresa:
            avisos.insert(0, "Serão excluídas também todas as unidades e contatos desta empresa.")
        return " ".join(aviso for aviso in avisos if aviso)

    def get_success_url(self) -> str:
        return reverse("clientes:lista")


class UnidadeDeleteView(ExclusaoConfirmadaView):
    model = Unidade
    permission_required = "clientes.delete_unidade"
    aviso = "Os contatos que atendem só esta unidade também serão excluídos."

    def get_aviso(self) -> str:
        pendencias = pendencias_que_saem_junto(self.object, "desta unidade")
        return f"{self.aviso} {pendencias}".strip()

    def get_success_url(self) -> str:
        return self.object.cliente.get_absolute_url()
