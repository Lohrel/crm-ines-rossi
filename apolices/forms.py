from django import forms

from apolices.models import DIAS_PARA_RENOVACAO, Contrato, Ramo, Seguradora
from clientes.documentos import CNPJ
from clientes.forms import BootstrapFormMixin, DocumentoField
from clientes.models import Cliente
from clientes.widgets import CampoData, EscolhaDeCor


class SeguradoraForm(BootstrapFormMixin, forms.ModelForm):
    cnpj = DocumentoField(CNPJ, required=False)
    # Endereço digitado sem "http" vira "https://...".
    site = forms.URLField(required=False, assume_scheme="https")

    class Meta:
        model = Seguradora
        fields = ["nome", "cnpj", "telefone", "site", "cor", "ativo"]
        widgets = {"cor": EscolhaDeCor}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cor"].choices = [("", "Sem cor"), *Seguradora.Cor.choices]

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
            *Contrato.CAMPOS_DO_SEGURO_DE_VIDA,
        ]
        widgets = {
            "inicio_vigencia": CampoData(),
            "data_renovacao": CampoData(),
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
        if self.instance.taxa_por_mil is not None:
            # Mostra 0.35, e não 0.350000.
            self.initial["taxa_por_mil"] = format(self.instance.taxa_por_mil.normalize(), "f")

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
    # Traz também os vigentes com a data de renovação já passada, que ficam no topo.
    renovacao = forms.BooleanField(
        label=f"Renovam nos próximos {DIAS_PARA_RENOVACAO} dias", required=False
    )
    vencimento = forms.IntegerField(
        label="Dia de vencimento", required=False, min_value=1, max_value=31
    )
