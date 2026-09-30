from django import forms

from apolices.models import Contrato, Ramo, Seguradora
from clientes.forms import BootstrapFormMixin
from clientes.models import Cliente, Unidade
from clientes.widgets import CampoData
from movimentacoes.forms import rotulo_do_plano

DATA = CampoData()


def por_cliente(registros, rotulo) -> list:
    """Opções agrupadas pelo cliente, para achar a filial ou o contrato certo na lista."""
    grupos: dict[str, list] = {}
    for registro in registros:
        grupos.setdefault(str(registro.cliente), []).append((registro.pk, rotulo(registro)))
    return list(grupos.items())


class EscolhaPorClienteMixin:
    """Filial e contrato de qualquer cliente, agrupados pelo nome do cliente."""

    def escolher_unidade_e_contrato(self) -> None:
        unidades = Unidade.objects.select_related("cliente").order_by(
            "cliente__nome", "-matriz", "razao_social"
        )
        contratos = Contrato.objects.select_related("cliente", "ramo", "seguradora").order_by(
            "cliente__nome", "ramo__nome", "numero"
        )
        if "unidade" in self.fields:
            self.fields["unidade"].choices = [("", "Todas"), *por_cliente(unidades, str)]
        self.fields["contrato"].choices = [("", "Todos"), *por_cliente(contratos, rotulo_do_plano)]


class FiltroVidasForm(EscolhaPorClienteMixin, BootstrapFormMixin, forms.Form):
    data = forms.DateField(label="Vidas em", widget=DATA, required=False)
    cliente = forms.ModelChoiceField(
        label="Empresa ou cliente",
        queryset=Cliente.objects.none(),
        required=False,
        empty_label="Todos",
    )
    unidade = forms.TypedChoiceField(label="Filial", coerce=int, empty_value=None, required=False)
    contrato = forms.TypedChoiceField(
        label="Contrato", coerce=int, empty_value=None, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(
            beneficiarios__isnull=False
        ).distinct()
        self.escolher_unidade_e_contrato()


class FiltroMovimentacoesForm(EscolhaPorClienteMixin, BootstrapFormMixin, forms.Form):
    POR_VIGENCIA = "vigencia"
    POR_ENVIO = "envio"
    TIPOS = [
        ("INC", "Inclusões"),
        ("EXC", "Exclusões"),
        ("ALT", "Alterações de plano"),
        ("todos", "Todos os tipos"),
    ]
    SITUACOES = [
        ("", "Todas"),
        ("aberto", "Em aberto"),
        ("CON", "Concluídas"),
        ("REJ", "Rejeitadas"),
        ("CAN", "Canceladas"),
    ]

    de = forms.DateField(label="De", widget=DATA)
    ate = forms.DateField(label="Até", widget=DATA)
    contar_por = forms.ChoiceField(
        label="Período pela",
        choices=[(POR_VIGENCIA, "Vigência"), (POR_ENVIO, "Envio à operadora")],
        required=False,
    )
    tipo = forms.ChoiceField(label="Tipo", choices=TIPOS, required=False)
    situacao = forms.ChoiceField(label="Situação", choices=SITUACOES, required=False)
    cliente = forms.ModelChoiceField(
        label="Empresa ou cliente",
        queryset=Cliente.objects.none(),
        required=False,
        empty_label="Todos",
    )
    contrato = forms.TypedChoiceField(
        label="Contrato", coerce=int, empty_value=None, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(
            movimentacoes__isnull=False
        ).distinct()
        self.escolher_unidade_e_contrato()

    def clean(self):
        dados = super().clean()
        de, ate = dados.get("de"), dados.get("ate")
        if de and ate and ate < de:
            self.add_error("ate", "Escolha uma data igual ou depois da primeira.")
        dados["tipo"] = dados.get("tipo") or "INC"
        dados["contar_por"] = dados.get("contar_por") or self.POR_VIGENCIA
        return dados


class FiltroApolicesForm(BootstrapFormMixin, forms.Form):
    renovacao_de = forms.DateField(label="Renovação de", widget=DATA, required=False)
    renovacao_ate = forms.DateField(label="até", widget=DATA, required=False)
    seguradora = forms.ModelChoiceField(
        label="Seguradora",
        queryset=Seguradora.objects.all(),
        required=False,
        empty_label="Todas",
    )
    ramo = forms.ModelChoiceField(
        label="Ramo", queryset=Ramo.objects.all(), required=False, empty_label="Todos"
    )
    situacao = forms.ChoiceField(
        label="Situação",
        choices=[("", "Vigentes"), ("todas", "Todas"), *Contrato.Situacao.choices],
        required=False,
    )

    def clean(self):
        dados = super().clean()
        de, ate = dados.get("renovacao_de"), dados.get("renovacao_ate")
        if de and ate and ate < de:
            self.add_error("renovacao_ate", "Escolha uma data igual ou depois da primeira.")
        return dados
