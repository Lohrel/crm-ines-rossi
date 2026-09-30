from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from apolices.models import Contrato
from clientes.forms import BootstrapFormMixin
from clientes.models import Cliente, Unidade
from clientes.widgets import CampoData
from movimentacoes.forms import rotulo_do_plano
from movimentacoes.models import ETAPAS_EM_ABERTO, Movimentacao
from pendencias.models import DIAS_DE_ANTECEDENCIA, Pendencia


def rotulo_da_unidade(unidade: Unidade) -> str:
    return f"{unidade} ({'matriz' if unidade.matriz else 'filial'})"


def rotulo_da_movimentacao(movimentacao: Movimentacao) -> str:
    etapa = movimentacao.get_etapa_display().lower()
    return f"{movimentacao} · {etapa} · pedido de {movimentacao.recebida_em:%d/%m/%Y}"


class PendenciaForm(BootstrapFormMixin, forms.ModelForm):
    """Pendência de um cliente: nas empresas, sempre com a unidade (matriz ou filial)."""

    class Meta:
        model = Pendencia
        fields = [
            "descricao",
            "unidade",
            "responsavel",
            "prazo",
            "contrato",
            "movimentacao",
            "observacao",
        ]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 2}),
            "prazo": CampoData(),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, cliente: Cliente, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:
            self.instance.cliente = cliente
            self.instance.registrada_por = usuario
            if usuario is not None:
                self.initial.setdefault("responsavel", usuario.pk)
        self.fields["responsavel"].queryset = get_user_model().objects.filter(
            Q(is_active=True) | Q(pk=self.instance.responsavel_id)
        )
        self._escolher_unidade(cliente)
        self._escolher_contrato(cliente)
        self._escolher_movimentacao(cliente)

    def _escolher_unidade(self, cliente: Cliente) -> None:
        if not cliente.eh_empresa:
            del self.fields["unidade"]
            return
        campo = self.fields["unidade"]
        campo.queryset = cliente.unidades.all()
        campo.required = True
        campo.empty_label = "Escolha a unidade"
        campo.label_from_instance = rotulo_da_unidade
        unidades = list(campo.queryset[:2])
        if len(unidades) == 1:
            self.initial.setdefault("unidade", unidades[0].pk)

    def _escolher_contrato(self, cliente: Cliente) -> None:
        contratos = cliente.contratos.select_related("ramo", "seguradora")
        if not contratos.exists():
            del self.fields["contrato"]
            return
        campo = self.fields["contrato"]
        campo.queryset = contratos
        campo.empty_label = "Nenhum"
        campo.label_from_instance = rotulo_do_plano

    def _escolher_movimentacao(self, cliente: Cliente) -> None:
        # As em aberto do cliente, e a que já estiver ligada (mesmo se terminou).
        atual = self.initial.get("movimentacao") or self.instance.movimentacao_id
        movimentacoes = (
            Movimentacao.objects.filter(cliente=cliente)
            .filter(Q(etapa__in=ETAPAS_EM_ABERTO) | Q(pk=getattr(atual, "pk", atual)))
            .select_related("beneficiario", "contrato__ramo")
        )
        if not movimentacoes.exists():
            del self.fields["movimentacao"]
            return
        campo = self.fields["movimentacao"]
        campo.queryset = movimentacoes
        campo.empty_label = "Nenhuma"
        campo.label_from_instance = rotulo_da_movimentacao
        campo.help_text = "As movimentações em aberto deste cliente."


class FiltroPendenciasForm(BootstrapFormMixin, forms.Form):
    # Em aberto e com o prazo vencido ou nos próximos dias (quadro do painel).
    ATENCAO = "atencao"
    SITUACOES = [
        ("", "Em aberto"),
        (ATENCAO, f"Pedem atenção ({DIAS_DE_ANTECEDENCIA} dias)"),
        ("concluidas", "Concluídas"),
        ("todas", "Todas"),
    ]

    q = forms.CharField(label="Buscar", required=False)
    situacao = forms.ChoiceField(label="Situação", choices=SITUACOES, required=False)
    responsavel = forms.ModelChoiceField(
        label="Responsável", queryset=None, required=False, empty_label="Todos"
    )
    # Vêm dos links do cliente, do contrato e da movimentação.
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.all(), required=False, widget=forms.HiddenInput
    )
    contrato = forms.ModelChoiceField(
        queryset=Contrato.objects.all(), required=False, widget=forms.HiddenInput
    )
    movimentacao = forms.ModelChoiceField(
        queryset=Movimentacao.objects.all(), required=False, widget=forms.HiddenInput
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Descrição, cliente ou filial"
        self.fields["responsavel"].queryset = get_user_model().objects.filter(is_active=True)
