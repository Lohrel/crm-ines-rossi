from django import forms
from django.core.exceptions import ValidationError

from clientes.documentos import CNPJ, CPF, Documento
from clientes.models import Cliente, Contato, Unidade

CAMPOS_ENDERECO = ["cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"]
CAMPOS_CONTATO = ["telefone", "whatsapp", "email"]


class DocumentoField(forms.CharField):
    """Campo de CPF/CNPJ: aceita com ou sem pontuação e guarda só os caracteres do número."""

    def __init__(self, documento: type[Documento], **kwargs):
        self.documento = documento
        kwargs.setdefault("label", documento.nome)
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("maxlength", "20")

    def to_python(self, value) -> str:
        return self.documento(super().to_python(value)).valor

    def prepare_value(self, value):
        return self.documento(value).formatado() if value else value


class BootstrapFormMixin:
    """Aplica as classes visuais do Bootstrap a todos os campos do formulário."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput | forms.CheckboxSelectMultiple):
                classe = "form-check-input"
            elif isinstance(widget, forms.Select):
                classe = "form-select"
            else:
                classe = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {classe}".strip()

    def full_clean(self):
        super().full_clean()
        for nome in self.errors:
            if nome in self.fields:
                widget = self.fields[nome].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()


class MarcacaoExclusivaFormMixin:
    """Permite marcar um novo registro exclusivo (matriz/contato principal).

    A validação de "só um marcado" é ignorada aqui porque o próprio modelo
    desmarca o anterior ao salvar.
    """

    def validate_unique(self):
        exclude = self._get_validation_exclusions()
        exclude.add(self._meta.model.campo_exclusivo)
        try:
            self.instance.validate_unique(exclude=exclude)
            self.instance.validate_constraints(exclude=exclude)
        except ValidationError as erro:
            self._update_errors(erro)


class PessoaFisicaForm(BootstrapFormMixin, forms.ModelForm):
    cpf = DocumentoField(CPF)

    class Meta:
        model = Cliente
        fields = [
            "nome",
            "cpf",
            "data_nascimento",
            "sexo",
            *CAMPOS_CONTATO,
            *CAMPOS_ENDERECO,
            "observacoes",
            "ativo",
        ]
        widgets = {
            "data_nascimento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tipo = Cliente.Tipo.PESSOA_FISICA
        self.fields["cpf"].widget.attrs["placeholder"] = "000.000.000-00"
        self.fields["cpf"].widget.attrs["inputmode"] = "numeric"


class EmpresaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "observacoes", "ativo"]
        labels = {"nome": "nome da empresa ou grupo"}
        help_texts = {
            "nome": "Ex.: Rede Supermercados Exemplo. As filiais são cadastradas como unidades."
        }
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tipo = Cliente.Tipo.PESSOA_JURIDICA
        self.instance.cpf = None


class UnidadeForm(MarcacaoExclusivaFormMixin, BootstrapFormMixin, forms.ModelForm):
    cnpj = DocumentoField(CNPJ)

    class Meta:
        model = Unidade
        fields = [
            "cnpj",
            "razao_social",
            "nome_fantasia",
            "matriz",
            *CAMPOS_CONTATO,
            *CAMPOS_ENDERECO,
            "ativo",
        ]
        help_texts = {"matriz": "Ao marcar, a matriz anterior (se houver) vira filial."}

    def __init__(self, *args, cliente: Cliente | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if cliente is not None:
            self.instance.cliente = cliente
        self.fields["cnpj"].widget.attrs["placeholder"] = "00.000.000/0000-00"


class ContatoForm(MarcacaoExclusivaFormMixin, BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Contato
        fields = ["nome", "cargo", *CAMPOS_CONTATO, "unidades", "principal"]
        help_texts = {
            "principal": "Ao marcar, o contato principal anterior da empresa deixa de ser.",
            "unidades": "Marque todas as unidades que esta pessoa atende.",
        }
        widgets = {"unidades": forms.CheckboxSelectMultiple}

    def __init__(self, *args, cliente: Cliente | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if cliente is not None:
            self.instance.cliente = cliente
        self.fields["unidades"].queryset = self.instance.cliente.unidades.all()

    def clean_unidades(self):
        unidades = list(self.cleaned_data["unidades"])
        self.instance.validar_unidades(unidades)
        return unidades


class BuscaClienteForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(label="Buscar", required=False)
    tipo = forms.ChoiceField(
        label="Tipo", required=False, choices=[("", "Todos"), *Cliente.Tipo.choices]
    )


class ConfirmacaoExclusaoForm(BootstrapFormMixin, forms.Form):
    """Pede que a pessoa digite o nome do registro antes de excluir."""

    confirmacao = forms.CharField(label="Digite o nome para confirmar")

    def __init__(self, *args, texto_esperado: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.texto_esperado = texto_esperado
        self.fields["confirmacao"].widget.attrs["autocomplete"] = "off"

    @staticmethod
    def _normalizar(texto: str) -> str:
        return " ".join(texto.split()).casefold()

    def clean_confirmacao(self) -> str:
        digitado = self.cleaned_data["confirmacao"]
        if self._normalizar(digitado) != self._normalizar(self.texto_esperado):
            raise ValidationError("O texto digitado não confere. Nada foi excluído.")
        return digitado
