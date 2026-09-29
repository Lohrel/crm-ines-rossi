from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from apolices.models import Contrato
from beneficiarios.forms import (
    AnexoForm,
    BuscaBeneficiarioForm,
    DependenteForm,
    EncerrarVinculoForm,
    TitularForm,
    VinculoForm,
)
from beneficiarios.historico import LinhaDoTempoDoBeneficiario
from beneficiarios.models import Anexo, Beneficiario, Vinculo
from beneficiarios.vidas import VidasDoCliente, filtro_de_ativos
from clientes.models import Cliente
from clientes.views import ExclusaoConfirmadaView, FormularioMixin


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
        contratos = list(cliente.contratos.select_related("ramo", "seguradora"))
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
    anexo = get_object_or_404(Anexo, pk=pk)
    resposta = FileResponse(
        anexo.arquivo.open("rb"), as_attachment=True, filename=anexo.nome_original
    )
    resposta["Cache-Control"] = "private, no-store"
    return resposta


class AnexoDeleteView(ExclusaoConfirmadaView):
    model = Anexo
    permission_required = "beneficiarios.delete_anexo"
    aviso = "O arquivo será apagado do servidor."

    def get_texto_esperado(self) -> str:
        return self.object.nome_original

    def get_success_url(self) -> str:
        return self.object.get_absolute_url()
