from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import modelform_factory

from apolices.models import Contrato
from beneficiarios.models import Beneficiario
from clientes.forms import BootstrapFormMixin
from clientes.models import Cliente
from movimentacoes.models import Etapa, Movimentacao

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def rotulo_do_plano(contrato: Contrato) -> str:
    texto = f"{contrato.ramo} · {contrato.seguradora} {contrato.numero}"
    return f"{texto} ({contrato.produto})" if contrato.produto else texto


class MovimentacaoForm(BootstrapFormMixin, forms.ModelForm):
    """Novo pedido de inclusão ou exclusão de uma pessoa num plano."""

    dependentes = forms.ModelMultipleChoiceField(
        label="Pedir também para os dependentes",
        queryset=Beneficiario.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Cria um pedido para cada dependente marcado, no mesmo plano e datas.",
    )

    class Meta:
        model = Movimentacao
        fields = ["contrato", "solicitante", "recebida_em", "enviada_em", "vigencia", "observacao"]
        widgets = {
            "recebida_em": DATA,
            "enviada_em": DATA,
            "vigencia": DATA,
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, tipo: str, beneficiario: Beneficiario, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tipo = tipo
        self.instance.beneficiario = beneficiario
        self.instance.cliente = beneficiario.cliente
        self.instance.registrada_por = usuario
        self.fields["contrato"].queryset = self._planos_possiveis(tipo, beneficiario)
        self.fields["contrato"].label_from_instance = rotulo_do_plano
        self.fields["solicitante"].queryset = beneficiario.cliente.contatos.all()
        self.fields["vigencia"].required = False
        self.initial.setdefault("recebida_em", date.today())
        dependentes = self._dependentes_possiveis(tipo, beneficiario)
        if dependentes is not None and dependentes.exists():
            self.fields["dependentes"].queryset = dependentes
        else:
            del self.fields["dependentes"]

    @staticmethod
    def _planos_possiveis(tipo: str, pessoa: Beneficiario):
        contratos = Contrato.objects.filter(cliente=pessoa.cliente).select_related(
            "ramo", "seguradora"
        )
        no_plano = pessoa.vinculos.filter(data_exclusao__isnull=True).values("contrato")
        if tipo == Movimentacao.Tipo.EXCLUSAO:
            return contratos.filter(pk__in=no_plano)
        contratos = contratos.vigentes().exclude(pk__in=no_plano)
        if not pessoa.eh_titular:
            # Planos em que o titular está ou está sendo incluído.
            titular = pessoa.titular
            do_titular = titular.vinculos.filter(data_exclusao__isnull=True).values("contrato")
            pedidos = titular.movimentacoes.em_aberto().filter(tipo=tipo).values("contrato")
            contratos = contratos.filter(Q(pk__in=do_titular) | Q(pk__in=pedidos))
        return contratos

    @staticmethod
    def _dependentes_possiveis(tipo: str, pessoa: Beneficiario):
        if not pessoa.eh_titular:
            return None
        if tipo == Movimentacao.Tipo.EXCLUSAO:
            # Na exclusão do titular os dependentes do plano saem junto, sem pedido próprio.
            return None
        return pessoa.dependentes.all()

    def clean(self):
        dados = super().clean()
        contrato = dados.get("contrato")
        for dependente in dados.get("dependentes") or []:
            pedido = Movimentacao(
                tipo=self.instance.tipo,
                cliente=dependente.cliente,
                beneficiario=dependente,
                contrato=contrato,
            )
            try:
                pedido.clean()
                pedido.validate_constraints()
            except ValidationError as erro:
                self.add_error("dependentes", f"{dependente}: {' '.join(erro.messages)}")
        return dados

    def save(self, commit=True):
        movimentacao = self.instance
        if movimentacao.enviada_em:
            movimentacao.etapa = Etapa.ENVIADA
        movimentacao = super().save(commit)
        if commit:
            for dependente in self.cleaned_data.get("dependentes") or []:
                Movimentacao.objects.create(
                    tipo=movimentacao.tipo,
                    cliente=movimentacao.cliente,
                    beneficiario=dependente,
                    contrato=movimentacao.contrato,
                    solicitante=movimentacao.solicitante,
                    recebida_em=movimentacao.recebida_em,
                    enviada_em=movimentacao.enviada_em,
                    vigencia=movimentacao.vigencia,
                    etapa=movimentacao.etapa,
                    observacao=movimentacao.observacao,
                    registrada_por=movimentacao.registrada_por,
                )
        return movimentacao


class EdicaoMovimentacaoForm(BootstrapFormMixin, forms.ModelForm):
    """Corrige dados do pedido sem mudar a etapa."""

    class Meta:
        model = Movimentacao
        fields = [
            "solicitante",
            "recebida_em",
            "enviada_em",
            "vigencia",
            "carteirinha",
            "carteirinha_enviada_em",
            "observacao",
        ]
        widgets = {
            "recebida_em": DATA,
            "enviada_em": DATA,
            "vigencia": DATA,
            "carteirinha_enviada_em": DATA,
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["solicitante"].queryset = self.instance.cliente.contatos.all()
        if self.instance.vinculo_id:
            # Depois de aprovada, a data já está no plano da pessoa.
            self.fields["vigencia"].disabled = True
        if not self.instance.eh_inclusao:
            del self.fields["carteirinha"]
            del self.fields["carteirinha_enviada_em"]


# Campos pedidos em cada mudança de etapa.
CAMPOS_DA_ETAPA = {
    Etapa.ENVIADA: ["enviada_em", "observacao"],
    Etapa.EM_ANALISE: ["observacao"],
    Etapa.APROVADA: ["vigencia", "carteirinha", "observacao"],
    Etapa.CONCLUIDA: ["carteirinha", "carteirinha_enviada_em", "observacao"],
    Etapa.REJEITADA: ["motivo_rejeicao", "observacao"],
    Etapa.CANCELADA: ["observacao"],
}
CAMPOS_SO_DE_INCLUSAO = {"carteirinha", "carteirinha_enviada_em"}


class MudancaDeEtapaFormBase(BootstrapFormMixin, forms.ModelForm):
    etapa: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome in CAMPOS_SO_DE_INCLUSAO & set(self.fields):
            if not self.instance.eh_inclusao:
                del self.fields[nome]
        hoje = date.today()
        for nome in ("enviada_em", "carteirinha_enviada_em"):
            if nome in self.fields:
                self.initial[nome] = getattr(self.instance, nome) or hoje
        if "motivo_rejeicao" in self.fields:
            self.fields["motivo_rejeicao"].required = True
        if "carteirinha" in self.fields and self.etapa == Etapa.CONCLUIDA:
            self.fields["carteirinha"].required = True

    def _post_clean(self):
        # A validação e a gravação ficam com Movimentacao.mudar_etapa.
        pass

    def save(self, commit=True):
        dados = {nome: self.cleaned_data[nome] for nome in self.fields}
        try:
            self.instance.mudar_etapa(self.etapa, **dados)
        except ValidationError as erro:
            self.add_error(None, erro)
            raise
        return self.instance


def formulario_da_etapa(etapa: str) -> type[MudancaDeEtapaFormBase]:
    return modelform_factory(
        Movimentacao,
        form=type("MudancaDeEtapaForm", (MudancaDeEtapaFormBase,), {"etapa": etapa}),
        fields=CAMPOS_DA_ETAPA[etapa],
        widgets={
            "enviada_em": DATA,
            "vigencia": DATA,
            "carteirinha_enviada_em": DATA,
            "observacao": forms.Textarea(attrs={"rows": 3}),
        },
    )


class FiltroMovimentacoesForm(BootstrapFormMixin, forms.Form):
    SITUACOES = [
        ("", "Em aberto"),
        ("CON", "Concluídas"),
        ("REJ", "Rejeitadas"),
        ("CAN", "Canceladas"),
        ("todas", "Todas"),
    ]

    q = forms.CharField(label="Buscar", required=False)
    situacao = forms.ChoiceField(label="Situação", choices=SITUACOES, required=False)
    mes = forms.CharField(
        label="Mês da vigência",
        required=False,
        widget=forms.DateInput(attrs={"type": "month"}),
    )
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.empresas(), required=False, empty_label="Todos os clientes"
    )
    tipo = forms.ChoiceField(
        choices=[("", "Inclusões e exclusões"), *Movimentacao.Tipo.choices], required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Nome, matrícula, carteirinha ou cliente"
        # Clientes pessoa física também podem ter movimentação.
        self.fields["cliente"].queryset = Cliente.objects.filter(
            movimentacoes__isnull=False
        ).distinct()

    def clean_mes(self) -> tuple[int, int] | None:
        texto = self.cleaned_data["mes"]
        if not texto:
            return None
        try:
            ano, mes = (int(parte) for parte in texto.split("-"))
            date(ano, mes, 1)
        except ValueError as erro:
            raise forms.ValidationError("Mês inválido.") from erro
        return ano, mes
