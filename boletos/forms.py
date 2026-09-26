from datetime import date

from django import forms

from apolices.models import Contrato
from boletos.models import Boleto, Situacao
from clientes.forms import BootstrapFormMixin, MesField
from clientes.widgets import CampoData

DATA = CampoData()
OBSERVACAO = forms.Textarea(attrs={"rows": 3})


def rotulo_do_contrato(contrato: Contrato) -> str:
    return f"{contrato.cliente} · {contrato.ramo} · {contrato.seguradora} {contrato.numero}"


def este_mes() -> date:
    return date.today().replace(day=1)


class ContatoDoClienteMixin:
    """O campo "enviado para" lista só os contatos do cliente do boleto."""

    def limitar_contatos(self, boleto: Boleto) -> None:
        contatos = boleto.contrato.cliente.contatos.all()
        if contatos.exists():
            self.fields["enviado_para"].queryset = contatos
        else:
            # Pessoa física não tem contatos cadastrados: o boleto vai para ela mesma.
            del self.fields["enviado_para"]


class BoletoForm(BootstrapFormMixin, forms.ModelForm):
    """Boleto lançado à mão, como coparticipação, reajuste ou caso especial."""

    referencia = MesField(label="Mês de referência")

    class Meta:
        model = Boleto
        fields = ["contrato", "tipo", "referencia", "vencimento", "valor", "observacao"]
        widgets = {"vencimento": DATA, "observacao": OBSERVACAO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        contratos = Contrato.objects.vigentes().select_related("cliente", "ramo", "seguradora")
        self.fields["contrato"].queryset = contratos.order_by("cliente__nome", "ramo__nome")
        self.fields["contrato"].label_from_instance = rotulo_do_contrato
        self.fields["vencimento"].required = False
        self.initial.setdefault("referencia", este_mes())


class EdicaoBoletoForm(ContatoDoClienteMixin, BootstrapFormMixin, forms.ModelForm):
    referencia = MesField(label="Mês de referência")

    class Meta:
        model = Boleto
        fields = [
            "tipo",
            "referencia",
            "vencimento",
            "valor",
            "enviado_em",
            "enviado_para",
            "cancelado",
            "observacao",
        ]
        widgets = {"vencimento": DATA, "enviado_em": DATA, "observacao": OBSERVACAO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vencimento"].required = False
        self.limitar_contatos(self.instance)


class EnvioForm(ContatoDoClienteMixin, BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Boleto
        fields = ["enviado_em", "enviado_para", "observacao"]
        widgets = {"enviado_em": DATA, "observacao": OBSERVACAO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enviado_em"].required = True
        self.limitar_contatos(self.instance)
        # Sugestões para o boleto ainda não enviado: hoje, para o contato principal.
        if not self.instance.enviado_em:
            self.initial["enviado_em"] = date.today()
        if "enviado_para" in self.fields and not self.instance.enviado_para_id:
            contatos = self.fields["enviado_para"].queryset
            self.initial["enviado_para"] = contatos.filter(principal=True).first()


class GerarMensalidadesForm(BootstrapFormMixin, forms.Form):
    referencia = MesField(
        label="Mês",
        help_text=(
            "Cria a mensalidade deste mês de cada contrato vigente em que a corretora envia "
            "o boleto, com o vencimento do contrato. As que já existem não são repetidas."
        ),
    )


class FiltroBoletosForm(BootstrapFormMixin, forms.Form):
    SITUACOES = [
        ("", "A enviar"),
        (Situacao.ENVIADO, "Enviados"),
        (Situacao.CANCELADO, "Cancelados"),
        ("todos", "Todos"),
    ]

    q = forms.CharField(label="Buscar", required=False)
    situacao = forms.ChoiceField(label="Situação", choices=SITUACOES, required=False)
    mes = MesField(label="Mês de referência", required=False)
    tipo = forms.ChoiceField(
        label="Tipo", choices=[("", "Todos os tipos"), *Boleto.Tipo.choices], required=False
    )
    fora = forms.BooleanField(label="Só fora do vencimento", required=False)
    contrato = forms.ModelChoiceField(
        queryset=Contrato.objects.all(), required=False, widget=forms.HiddenInput
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Cliente ou número do contrato"
