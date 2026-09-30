from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import modelform_factory

from apolices.models import Contrato
from beneficiarios.models import Beneficiario
from clientes.forms import BootstrapFormMixin, MesField
from clientes.models import Cliente
from clientes.widgets import CampoData
from movimentacoes.models import Etapa, Movimentacao

DATA = CampoData()
ENTRADAS = [Movimentacao.Tipo.INCLUSAO, Movimentacao.Tipo.ALTERACAO]
# Na alteração, a vigência é quando a pessoa entra no novo plano (e sai do atual).
VIGENCIA_DA_ALTERACAO = "Início no novo plano"


def rotulo_do_plano(contrato: Contrato) -> str:
    texto = f"{contrato.ramo} · {contrato.seguradora} {contrato.numero}"
    return f"{texto} ({contrato.produto})" if contrato.produto else texto


class MovimentacaoForm(BootstrapFormMixin, forms.ModelForm):
    """Novo pedido de inclusão, exclusão ou alteração de plano de uma pessoa."""

    dependentes = forms.ModelMultipleChoiceField(
        label="Pedir também para os dependentes",
        queryset=Beneficiario.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Cria um pedido para cada dependente marcado, no mesmo plano e datas.",
    )

    class Meta:
        model = Movimentacao
        fields = [
            "contrato_anterior",
            "contrato",
            "solicitante",
            "recebida_em",
            "enviada_em",
            "vigencia",
            "observacao",
        ]
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
        if tipo == Movimentacao.Tipo.ALTERACAO:
            self._preparar_alteracao(beneficiario)
        else:
            del self.fields["contrato_anterior"]
        self.fields["solicitante"].queryset = beneficiario.cliente.contatos.all()
        self.fields["vigencia"].required = False
        # Só se registra o pedido depois de enviado à operadora.
        self.fields["enviada_em"].required = True
        for nome in ("recebida_em", "enviada_em"):
            self.initial.setdefault(nome, date.today())
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
            # Planos em que o titular está ou está entrando.
            titular = pessoa.titular
            do_titular = titular.vinculos.filter(data_exclusao__isnull=True).values("contrato")
            pedidos = titular.movimentacoes.em_aberto().filter(tipo__in=ENTRADAS).values("contrato")
            contratos = contratos.filter(Q(pk__in=do_titular) | Q(pk__in=pedidos))
        return contratos

    def _preparar_alteracao(self, pessoa: Beneficiario) -> None:
        """Sai de um dos planos atuais e entra noutro do mesmo ramo."""
        anterior = self.fields["contrato_anterior"]
        anterior.required = True
        anterior.label = "Plano atual (sai dele)"
        anterior.help_text = ""
        anterior.empty_label = "Escolha o plano atual"
        anterior.label_from_instance = rotulo_do_plano
        anterior.queryset = Contrato.objects.filter(
            pk__in=pessoa.vinculos.filter(data_exclusao__isnull=True).values("contrato")
        ).select_related("ramo", "seguradora")
        novo = self.fields["contrato"]
        novo.label = "Novo plano"
        novo.queryset = novo.queryset.filter(ramo__in=anterior.queryset.values("ramo"))
        vigencia = self.fields["vigencia"]
        vigencia.label = VIGENCIA_DA_ALTERACAO
        vigencia.help_text = f"O plano atual termina nesta data. {vigencia.help_text}"
        # Vindo do botão "Alterar plano" de um dos planos, ele fica fixo.
        escolhido = anterior.queryset.filter(pk=self.initial.get("contrato_anterior")).first()
        if escolhido:
            anterior.disabled = True
            anterior.empty_label = None
            anterior.queryset = anterior.queryset.filter(pk=escolhido.pk)
            novo.queryset = novo.queryset.filter(ramo=escolhido.ramo)
            opcoes = list(novo.queryset[:2])
            if len(opcoes) == 1:
                self.initial.setdefault("contrato", opcoes[0].pk)

    @staticmethod
    def _dependentes_possiveis(tipo: str, pessoa: Beneficiario):
        if not pessoa.eh_titular:
            return None
        if tipo != Movimentacao.Tipo.INCLUSAO:
            # Na exclusão e na alteração do titular, os dependentes do plano vão junto.
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
        self.fields["enviada_em"].required = True
        if self.instance.vinculo_id:
            # Depois de aprovada, a data já está no plano da pessoa.
            self.fields["vigencia"].disabled = True
        if self.instance.eh_alteracao:
            self.fields["vigencia"].label = VIGENCIA_DA_ALTERACAO
        if not self.instance.eh_inclusao:
            del self.fields["carteirinha"]
            del self.fields["carteirinha_enviada_em"]

    def save(self, commit=True):
        movimentacao = super().save(commit)
        vinculo = movimentacao.vinculo
        # A carteirinha corrigida aqui também vale no plano da pessoa.
        mudou = (
            vinculo and movimentacao.eh_inclusao and vinculo.carteirinha != movimentacao.carteirinha
        )
        if commit and mudou:
            vinculo.carteirinha = movimentacao.carteirinha
            vinculo.save(update_fields=["carteirinha", "atualizado_em"])
        return movimentacao


# Campos pedidos em cada mudança de etapa.
CAMPOS_DA_ETAPA = {
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
        if "carteirinha_enviada_em" in self.fields:
            self.initial["carteirinha_enviada_em"] = (
                self.instance.carteirinha_enviada_em or date.today()
            )
        if "motivo_rejeicao" in self.fields:
            self.fields["motivo_rejeicao"].required = True
        if "carteirinha" in self.fields and self.etapa == Etapa.CONCLUIDA:
            self.fields["carteirinha"].required = True
        if "vigencia" in self.fields and self.instance.eh_alteracao:
            self.fields["vigencia"].label = VIGENCIA_DA_ALTERACAO

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
    mes = MesField(label="Mês da vigência", required=False)
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.empresas(), required=False, empty_label="Todos os clientes"
    )
    tipo = forms.ChoiceField(
        choices=[("", "Todos os tipos"), *Movimentacao.Tipo.choices], required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Nome, matrícula, carteirinha ou cliente"
        # Clientes pessoa física também podem ter movimentação.
        self.fields["cliente"].queryset = Cliente.objects.filter(
            movimentacoes__isnull=False
        ).distinct()


class PlanilhaForm(BootstrapFormMixin, forms.Form):
    """Empresa e mês da planilha de controle das inclusões."""

    cliente = forms.ModelChoiceField(
        label="Empresa ou cliente", queryset=Cliente.objects.none(), empty_label="Escolha"
    )
    mes = MesField(label="Mês da digitação")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(contratos__isnull=False).distinct()
