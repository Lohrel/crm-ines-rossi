from django import forms

from apolices.models import Contrato, Ramo, Seguradora
from clientes.documentos import CNPJ
from clientes.forms import BootstrapFormMixin, DocumentoField
from clientes.models import Cliente


class SeguradoraForm(BootstrapFormMixin, forms.ModelForm):
    cnpj = DocumentoField(CNPJ, required=False)
    # Endereço digitado sem "http" vira "https://...".
    site = forms.URLField(required=False, assume_scheme="https")

    class Meta:
        model = Seguradora
        fields = ["nome", "cnpj", "telefone", "site", "ativo"]

    def clean_cnpj(self):
        # Vazio vira None para não conflitar com outras seguradoras sem CNPJ.
        return self.cleaned_data["cnpj"] or None


class ContratoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Contrato
        fields = [
            "seguradora",
            "ramo",
            "numero",
            "produto",
            "modalidade",
            "situacao",
            "inicio_vigencia",
            "data_renovacao",
            "dia_vencimento",
            "dia_fechamento",
            "valor_mensal",
            "corretora_envia_boleto",
            "coparticipacao",
            "unidades",
            "observacoes",
        ]
        widgets = {
            "inicio_vigencia": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_renovacao": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "unidades": forms.CheckboxSelectMultiple,
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, cliente: Cliente | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if cliente is not None:
            self.instance.cliente = cliente
        cliente = self.instance.cliente
        self.fields["seguradora"].queryset = Seguradora.objects.filter(ativo=True)
        self.fields["ramo"].queryset = Ramo.objects.filter(ativo=True)
        if self.instance.pk:
            # Mantém seguradora/ramo inativos que o contrato já usa.
            self.fields["seguradora"].queryset |= Seguradora.objects.filter(
                pk=self.instance.seguradora_id
            )
            self.fields["ramo"].queryset |= Ramo.objects.filter(pk=self.instance.ramo_id)
        if cliente.eh_empresa:
            self.fields["unidades"].queryset = cliente.unidades.all()
            self.initial.setdefault("modalidade", Contrato.Modalidade.EMPRESARIAL)
        else:
            del self.fields["unidades"]
            self.initial.setdefault("modalidade", Contrato.Modalidade.INDIVIDUAL)

    def clean(self):
        dados = super().clean()
        if "unidades" in self.fields and dados.get("unidades") is not None:
            try:
                self.instance.validar_unidades(list(dados["unidades"]))
            except forms.ValidationError as erro:
                self.add_error(None, erro)
        return dados


class FiltroContratosForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(label="Buscar", required=False)
    seguradora = forms.ModelChoiceField(
        Seguradora.objects.all(), required=False, empty_label="Todas as seguradoras"
    )
    ramo = forms.ModelChoiceField(Ramo.objects.all(), required=False, empty_label="Todos os ramos")
    situacao = forms.ChoiceField(
        label="Situação",
        required=False,
        choices=[("", "Vigentes"), ("todas", "Todas"), *Contrato.Situacao.choices],
    )
    boleto = forms.BooleanField(label="Só boletos enviados pela corretora", required=False)
    vencimento = forms.IntegerField(
        label="Dia de vencimento", required=False, min_value=1, max_value=31
    )
