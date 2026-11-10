from django import forms

from apolices.models import Contrato, Ramo, Seguradora
from boletos.models import meses_entre
from clientes.forms import BootstrapFormMixin, MesField
from clientes.models import Cliente, Unidade
from clientes.widgets import CampoData
from movimentacoes.forms import rotulo_do_plano
from relatorios.indicadores import MAXIMO_DE_MESES

DATA = CampoData()


def por_cliente(registros, rotulo) -> list:
    """Opções agrupadas pelo cliente, para achar a filial ou o contrato certo na lista."""
    grupos: dict[str, list] = {}
    for registro in registros:
        grupos.setdefault(str(registro.cliente), []).append((registro.pk, rotulo(registro)))
    return list(grupos.items())


class SelectDoCliente(forms.Select):
    """Lista de filiais ou de contratos em que cada opção diz de qual cliente é
    (data-cliente), para static/js/filtro-por-cliente.js esconder as dos outros clientes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cliente_de: dict[str, int] = {}
        self.attrs["data-filtra-pelo-cliente"] = ""

    def create_option(self, name, value, *args, **kwargs):
        opcao = super().create_option(name, value, *args, **kwargs)
        if (cliente := self.cliente_de.get(str(value))) is not None:
            opcao["attrs"]["data-cliente"] = cliente
        return opcao


class EscolhaPorClienteMixin:
    """Filial e contrato agrupados pelo nome do cliente. Escolhida uma empresa, a tela mostra só
    as filiais e os contratos dela, e o servidor ignora uma filial ou um contrato de outra."""

    def cliente_escolhido(self) -> int | None:
        valor = str(self.data.get("cliente", "")) if self.is_bound else ""
        return int(valor) if valor.isdigit() else None

    def escolher_unidade_e_contrato(self) -> None:
        unidades = Unidade.objects.select_related("cliente").order_by(
            "cliente__nome", "-matriz", "razao_social"
        )
        contratos = Contrato.objects.de_pessoas().select_related("cliente", "ramo", "seguradora")
        contratos = contratos.order_by("cliente__nome", "ramo__nome", "numero")
        campos = [("contrato", contratos, rotulo_do_plano, "Todos")]
        if "unidade" in self.fields:
            campos.insert(0, ("unidade", unidades, str, "Todas"))
        for nome, registros, rotulo, vazio in campos:
            registros = list(registros)
            campo = self.fields[nome]
            campo.widget = SelectDoCliente(attrs=campo.widget.attrs)
            campo.widget.cliente_de = {str(r.pk): r.cliente_id for r in registros}
            campo.choices = [("", vazio), *por_cliente(registros, rotulo)]
            # A filial ou o contrato de outra empresa (a empresa mudou e a filial ficou)
            # é ignorado, em vez de misturar os dois filtros e não achar nada.
            escolhido = str(self.data.get(nome, "")) if self.is_bound else ""
            cliente = self.cliente_escolhido()
            if escolhido and cliente and campo.widget.cliente_de.get(escolhido) != cliente:
                self.data = self.data.copy()
                self.data[nome] = ""


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


class FiltroIndicadoresForm(BootstrapFormMixin, forms.Form):
    de = MesField(label="Do mês")
    ate = MesField(label="Até o mês")
    cliente = forms.ModelChoiceField(
        label="Empresa ou cliente",
        queryset=Cliente.objects.all(),
        required=False,
        empty_label="Todos (geral)",
    )

    def clean(self):
        dados = super().clean()
        de, ate = dados.get("de"), dados.get("ate")
        if de and ate and ate < de:
            self.add_error("ate", "Escolha um mês igual ou depois do primeiro.")
        elif de and ate and len(meses_entre(de, ate)) > MAXIMO_DE_MESES:
            self.add_error("ate", f"Escolha até {MAXIMO_DE_MESES} meses de uma vez.")
        return dados
