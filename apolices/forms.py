import re

from django import forms

from apolices.models import (
    DIAS_PARA_RENOVACAO,
    PLACA,
    BemSegurado,
    Contrato,
    DocumentoDaSeguradora,
    Plano,
    Ramo,
    Seguradora,
    limpar_placa,
)
from clientes.documentos import CNPJ
from clientes.forms import (
    ArquivoAnexadoForm,
    BootstrapFormMixin,
    CpfOuCnpjField,
    DocumentoField,
)
from clientes.models import Cliente
from clientes.widgets import CampoData, EscolhaDeCor


def rotulo_do_contrato(contrato: Contrato) -> str:
    texto = f"{contrato.ramo} · {contrato.seguradora} {contrato.numero}"
    return f"{texto} ({contrato.produto})" if contrato.produto else texto


class PlanoDoContratoField(forms.ChoiceField):
    """O contrato e, se ele tiver planos cadastrados, o plano, numa lista só.

    Os planos de um contrato aparecem agrupados debaixo dele (ex.: TNPQ e TNP4). O valor
    limpo é o par (contrato, plano), com o plano None nos contratos sem planos cadastrados.
    Nas listas de contratos, use prefetch_related("planos").
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label", "Plano")
        # Criado depois do BootstrapFormMixin aplicar as classes nos campos do formulário.
        kwargs.setdefault("widget", forms.Select(attrs={"class": "form-select"}))
        super().__init__(*args, **kwargs)
        self.opcoes: dict[str, tuple[Contrato, Plano | None]] = {}

    @staticmethod
    def valor(contrato: Contrato, plano: Plano | None = None) -> str:
        # O contrato sem planos usa o próprio número, como a lista de contratos usava antes.
        return f"p{plano.pk}" if plano else str(contrato.pk)

    def definir(self, contratos, fora=()) -> None:
        """Monta a lista. `fora` são os pares (contrato_id, plano_id) que ficam de fora."""
        fora = set(fora)
        self.opcoes = {}
        escolhas = [("", "Escolha o plano")]
        for contrato in contratos:
            if contrato.tem_planos:
                grupo = []
                for plano in contrato.planos_ativos:
                    if (contrato.pk, plano.pk) not in fora:
                        self.opcoes[self.valor(contrato, plano)] = (contrato, plano)
                        grupo.append((self.valor(contrato, plano), plano.nome))
                if grupo:
                    escolhas.append((rotulo_do_contrato(contrato), grupo))
            elif (contrato.pk, None) not in fora:
                self.opcoes[self.valor(contrato)] = (contrato, None)
                escolhas.append((self.valor(contrato), rotulo_do_contrato(contrato)))
        self.choices = escolhas

    def clean(self, value):
        valor = super().clean(value)
        return self.opcoes.get(valor) if valor else None


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


class DocumentoDaSeguradoraForm(ArquivoAnexadoForm):
    campo_do_dono = "seguradora"

    class Meta:
        model = DocumentoDaSeguradora
        fields = ["tipo", "ramo", "descricao", "arquivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ramo"].queryset = Ramo.objects.filter(ativo=True)
        self.fields["ramo"].empty_label = "Todos os ramos"


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


class PlanoForm(BootstrapFormMixin, forms.ModelForm):
    """Nome de um plano do contrato (ex.: TNPQ) e se ele ainda é oferecido."""

    class Meta:
        model = Plano
        fields = ["nome", "ativo"]

    def __init__(self, *args, contrato: Contrato | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if contrato is not None:
            self.instance.contrato = contrato
        if not self.instance.pk:
            del self.fields["ativo"]

    def clean_nome(self):
        nome = " ".join(self.cleaned_data["nome"].split())
        # O contrato não está no formulário: a regra do nome repetido é conferida aqui.
        repetidos = Plano.objects.filter(contrato=self.instance.contrato, nome__iexact=nome)
        if repetidos.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Este contrato já tem um plano com este nome.")
        return nome


class FiltroContratosForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(label="Buscar", required=False)
    seguradora = forms.ModelChoiceField(
        Seguradora.objects.all(),
        required=False,
        empty_label="Todas as seguradoras",
        widget=forms.Select(attrs={"aria-label": "Seguradora"}),
    )
    ramo = forms.ModelChoiceField(
        Ramo.objects.all(),
        required=False,
        empty_label="Todos os ramos",
        widget=forms.Select(attrs={"aria-label": "Ramo"}),
    )
    situacao = forms.ChoiceField(
        label="Situação",
        required=False,
        choices=[("", "Vigentes"), ("todas", "Todas"), *Contrato.Situacao.choices],
        widget=forms.Select(attrs={"aria-label": "Situação"}),
    )
    boleto = forms.BooleanField(label="Só boletos enviados pela corretora", required=False)
    # Traz também os vigentes com a data de renovação já passada, que ficam no topo.
    renovacao = forms.BooleanField(
        label=f"Renovam nos próximos {DIAS_PARA_RENOVACAO} dias", required=False
    )
    vencimento = forms.IntegerField(
        label="Dia de vencimento", required=False, min_value=1, max_value=31
    )


class PlacaField(forms.CharField):
    """Placa antiga (ABC-1234) ou do Mercosul (ABC1D23); guarda sem traço, em maiúsculas."""

    def __init__(self, **kwargs):
        kwargs.setdefault("help_text", "Ex.: ABC1D23 ou ABC-1234.")
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("maxlength", "8")

    def to_python(self, value) -> str:
        return limpar_placa(super().to_python(value))

    def validate(self, value) -> None:
        super().validate(value)
        if value and not PLACA.fullmatch(value):
            raise forms.ValidationError("Placa inválida. Use ABC1D23 ou ABC-1234.")


class RenavamField(forms.CharField):
    """Renavam com 9 ou 11 números; aceita o número colado com pontuação e guarda só os números."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.widget.attrs.update(maxlength="15", inputmode="numeric")

    def to_python(self, value) -> str:
        return re.sub(r"\D", "", super().to_python(value))

    def validate(self, value) -> None:
        super().validate(value)
        if value and len(value) not in (9, 11):
            raise forms.ValidationError("O Renavam tem 9 ou 11 números.")


# Os campos de cada um, nos blocos do formulário e da página do veículo ou do imóvel.
BLOCOS_DO_VEICULO = {
    "Veículo": [
        "descricao",
        "placa",
        "ano_modelo",
        "cor",
        "combustivel",
        "renavam",
        "proprietario",
        "documento_proprietario",
        "condutor_principal",
        "cep",
        "condutor_jovem",
    ],
    "Coberturas e prêmio": [
        "danos_materiais",
        "danos_corporais",
        "danos_morais",
        "premio",
        "observacao",
    ],
}
BLOCOS_DO_IMOVEL = {
    "Imóvel": [
        "descricao",
        "cep",
        "logradouro",
        "numero",
        "complemento",
        "bairro",
        "cidade",
        "uf",
        "proprietario",
        "documento_proprietario",
    ],
    "Capitais e prêmio": ["capitais", "premio", "observacao"],
}


class BemSeguradoForm(BootstrapFormMixin, forms.ModelForm):
    """Base do veículo e do imóvel: o mesmo cadastro, com os campos de cada um."""

    blocos: dict[str, list[str]] = {}
    documento_proprietario = CpfOuCnpjField(label="CPF/CNPJ do proprietário", required=False)

    class Meta:
        model = BemSegurado
        fields: list[str] = []
        widgets = {
            "capitais": forms.Textarea(attrs={"rows": 3}),
            "observacao": forms.Textarea(attrs={"rows": 2}),
        }


class VeiculoForm(BemSeguradoForm):
    blocos = BLOCOS_DO_VEICULO
    placa = PlacaField(required=False)
    renavam = RenavamField(label="Renavam", required=False)

    class Meta(BemSeguradoForm.Meta):
        fields = [campo for campos in BLOCOS_DO_VEICULO.values() for campo in campos]
        labels = {"descricao": "Marca e modelo", "cep": "CEP de pernoite"}
        help_texts = {"descricao": "Com a versão, como no documento do veículo."}


class ImovelForm(BemSeguradoForm):
    blocos = BLOCOS_DO_IMOVEL

    class Meta(BemSeguradoForm.Meta):
        fields = [campo for campos in BLOCOS_DO_IMOVEL.values() for campo in campos]
        labels = {"descricao": "Tipo de imóvel"}
        help_texts = {"descricao": "Ex.: casa, apartamento, comercial."}
