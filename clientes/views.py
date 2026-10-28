import logging

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from beneficiarios.vidas import VidasDoCliente, anotar_vidas
from clientes.forms import (
    BuscaClienteForm,
    ConfirmacaoExclusaoForm,
    ContatoForm,
    DocumentoDoClienteForm,
    EmpresaForm,
    PessoaFisicaForm,
    UnidadeForm,
)
from clientes.historico import LinhaDoTempo
from clientes.models import Cliente, Contato, DocumentoDoCliente, Unidade

logger = logging.getLogger(__name__)


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
        contexto["documentos"] = self.object.documentos.select_related(
            "enviado_por", "contrato__ramo", "contrato__seguradora"
        )
        contexto["pendencias"] = self.object.pendencias.em_aberto().para_tabela()
        contratos = self.object.contratos.select_related("seguradora", "ramo")
        contratos = list(anotar_vidas(contratos.prefetch_related("unidades", "bens", "planos")))
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


# Campo oculto dos formulários de edição: quando o registro foi gravado pela última vez.
CAMPO_DA_VERSAO = "versao_gravada"


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

    # ------------------------------------------------------------------
    # Duas pessoas editando o mesmo registro ao mesmo tempo
    # ------------------------------------------------------------------

    def get_form(self, form_class=None):
        """Na edição, guarda num campo oculto quando o registro foi gravado pela última vez.

        Se outra pessoa gravar o registro enquanto esta edita, o formulário não é gravado:
        sem isso, a segunda pessoa apagaria sem saber o que a primeira acabou de gravar.
        """
        form = super().get_form(form_class)
        if versao := self._versao_gravada():
            form.fields[CAMPO_DA_VERSAO] = forms.CharField(widget=forms.HiddenInput, required=False)
            form.initial[CAMPO_DA_VERSAO] = versao
            setattr(form, f"clean_{CAMPO_DA_VERSAO}", lambda: self._conferir_versao(form))
        return form

    def _versao_gravada(self) -> str:
        objeto = getattr(self, "object", None)
        gravado_em = getattr(objeto, "atualizado_em", None) if objeto and objeto.pk else None
        return gravado_em.isoformat() if gravado_em else ""

    def _conferir_versao(self, form) -> str:
        lida = form.cleaned_data.get(CAMPO_DA_VERSAO, "")
        atual = self._versao_gravada()
        # Vazio: a tela foi aberta antes desta conferência existir.
        if lida and lida != atual:
            form.add_error(None, self._aviso_de_edicao_simultanea())
            # Se a pessoa salvar de novo depois de conferir, vale o que está na tela.
            form.data = form.data.copy()
            form.data[form.add_prefix(CAMPO_DA_VERSAO)] = atual
        return lida

    def _aviso_de_edicao_simultanea(self) -> str:
        historico = getattr(self.object, "history", None)
        ultima = historico.first() if historico is not None else None
        usuario = ultima.history_user if ultima else None
        quem = (usuario.get_full_name() or usuario.username) if usuario else "Outra pessoa"
        hora = timezone.localtime(self.object.atualizado_em).strftime("%H:%M")
        return (
            f"{quem} gravou este registro às {hora}, enquanto você editava, e a sua alteração "
            "ainda não foi gravada. Abra o registro em outra aba para ver o que mudou. Se salvar "
            "de novo, o que está nesta tela substitui o que foi gravado."
        )


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
    dica_bloqueio = (
        "Remova ou transfira esses registros antes. "
        'Se o objetivo é só parar de usar, edite e desmarque "Ativo".'
    )

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
        contexto["dica_bloqueio"] = self.dica_bloqueio
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
        if quantos := self.object.documentos.count():
            avisos.append(
                "O documento anexado também será apagado do servidor."
                if quantos == 1
                else f"Os {quantos} documentos anexados também serão apagados do servidor."
            )
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


# ------------------------------------------------------------------
# Arquivos anexados (documentos do cliente e da seguradora)
# ------------------------------------------------------------------


def entregar_arquivo(request, anexado):
    """Entrega o arquivo só para quem está logado (o login é exigido pelo middleware)."""
    try:
        arquivo = anexado.arquivo.open("rb")
    except FileNotFoundError:
        # O registro existe, mas o arquivo sumiu do disco: o backup dos anexos o tem.
        logger.error("Arquivo anexado não encontrado no disco: %s", anexado.arquivo.name)
        messages.error(
            request,
            f"O arquivo “{anexado.nome_original}” não foi encontrado no servidor. Avise quem "
            "cuida do sistema: ele pode ser recuperado do backup dos anexos.",
        )
        return redirect(anexado.get_absolute_url())
    resposta = FileResponse(arquivo, as_attachment=True, filename=anexado.nome_original)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


class ArquivoAnexadoCreateView(FormularioMixin, CreateView):
    """Envio de um arquivo para um registro (o "dono"), com quem enviou."""

    modelo_do_dono: type
    mensagem_sucesso = "Arquivo anexado."
    texto_do_botao = "Anexar"

    def get_dono(self):
        if not hasattr(self, "dono"):
            self.dono = get_object_or_404(self.modelo_do_dono, pk=self.kwargs["dono_pk"])
        return self.dono

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "dono": self.get_dono(), "usuario": self.request.user}

    def get_titulo(self) -> str:
        return f"Anexar documento de {self.get_dono()}"

    def get_url_cancelar(self) -> str:
        return f"{self.get_dono().get_absolute_url()}#documentos"


class ArquivoAnexadoDeleteView(ExclusaoConfirmadaView):
    aviso = "O arquivo será apagado do servidor."

    def get_texto_esperado(self) -> str:
        return self.object.nome_original

    def get_success_url(self) -> str:
        return self.object.get_absolute_url()


class DocumentoDoClienteCreateView(ArquivoAnexadoCreateView):
    model = DocumentoDoCliente
    modelo_do_dono = Cliente
    form_class = DocumentoDoClienteForm


def baixar_documento(request, pk: int):
    return entregar_arquivo(request, get_object_or_404(DocumentoDoCliente, pk=pk))


class DocumentoDoClienteDeleteView(ArquivoAnexadoDeleteView):
    model = DocumentoDoCliente
    permission_required = "clientes.delete_documentodocliente"
