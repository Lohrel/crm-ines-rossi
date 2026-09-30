import re
from datetime import date, datetime

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from clientes.documentos import CNPJ, CPF, Documento, cpf_ou_cnpj
from clientes.models import Cliente, Contato, Unidade
from clientes.planilhas import PlanilhaInvalidaError
from clientes.widgets import CampoData

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


class CpfOuCnpjField(forms.CharField):
    """CPF ou CNPJ (que pode ter letras), com ou sem pontuação; guarda só os caracteres."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("maxlength", "20")

    def to_python(self, value) -> str:
        return re.sub(r"[^0-9A-Z]", "", super().to_python(value).upper())

    def validate(self, value) -> None:
        super().validate(value)
        documento = cpf_ou_cnpj(value)
        if value and not (documento and documento.valido()):
            raise ValidationError("CPF ou CNPJ inválido.")

    def prepare_value(self, value):
        documento = cpf_ou_cnpj(value) if value else None
        return documento.formatado() if documento else value


class MesField(forms.Field):
    """Mês digitado como mm/aaaa (ex.: 09/2026). Devolve o dia 1º desse mês."""

    FORMATOS = ("%m/%Y", "%Y-%m")
    # data-campo-mes: static/js/campos-data.js coloca a barra e seleciona o mês ao clicar.
    widget = forms.TextInput(
        attrs={
            "placeholder": "mm/aaaa",
            "inputmode": "numeric",
            "autocomplete": "off",
            "maxlength": "7",
            "data-campo-mes": "",
        }
    )
    default_error_messages = {"invalid": "Mês inválido. Use mm/aaaa, por exemplo 09/2026."}

    def to_python(self, value) -> date | None:
        texto = (value or "").strip()
        if not texto:
            return None
        for formato in self.FORMATOS:
            try:
                return datetime.strptime(texto, formato).date()
            except ValueError:
                continue
        raise ValidationError(self.error_messages["invalid"], code="invalid")

    def prepare_value(self, value):
        return value.strftime("%m/%Y") if isinstance(value, date) else value


class SecaoDoFormulario:
    """Alguns campos de um formulário, num cartão próprio (ver clientes/_campos.html).

    Só a seção principal mostra os campos ocultos e os erros gerais do formulário.
    """

    def __init__(self, form: forms.BaseForm, campos: list[str], principal: bool = False) -> None:
        self.form = form
        self.campos = campos
        self.principal = principal

    def hidden_fields(self):
        return self.form.hidden_fields() if self.principal else []

    def non_field_errors(self):
        return self.form.non_field_errors() if self.principal else []

    def visible_fields(self):
        return [campo for campo in self.form.visible_fields() if campo.name in self.campos]


class BootstrapFormMixin:
    """Aplica as classes visuais do Bootstrap a todos os campos do formulário."""

    # Opção vazia das listas de escolha, no lugar do "---------" do Django.
    OPCAO_VAZIA = "Escolha"

    def __init__(self, *args, **kwargs):
        # Rótulos sem os dois pontos no fim ("Buscar", e não "Buscar:"), como nos cadastros.
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            # O RadioSelect inclui o CheckboxSelectMultiple, que é uma subclasse dele.
            if isinstance(widget, forms.CheckboxInput | forms.RadioSelect):
                classe = "form-check-input"
            elif isinstance(widget, forms.Select):
                classe = "form-select"
            else:
                classe = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {classe}".strip()
            self._trocar_opcao_vazia(campo)

    def _trocar_opcao_vazia(self, campo: forms.Field) -> None:
        tracejado = "---------"
        if isinstance(campo, forms.ModelChoiceField):
            if campo.empty_label == tracejado:
                campo.empty_label = self.OPCAO_VAZIA
        elif isinstance(campo, forms.ChoiceField):
            campo.choices = [
                (valor, self.OPCAO_VAZIA if valor == "" and rotulo == tracejado else rotulo)
                for valor, rotulo in campo.choices
            ]

    def full_clean(self):
        super().full_clean()
        for nome in self.errors:
            if nome in self.fields:
                self._sem_aviso_repetido(nome)
                widget = self.fields[nome].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()

    def _sem_aviso_repetido(self, nome: str) -> None:
        # Campo vazio que o modelo também cobra (ex.: a filial nas empresas): fica só o aviso
        # do modelo, que diz o que falta, em vez de "Este campo é obrigatório." junto.
        erros = self.errors[nome].as_data()
        especificos = [erro for erro in erros if erro.code != "required"]
        if especificos and len(especificos) < len(erros):
            self.errors[nome] = self.error_class(especificos, renderer=self.renderer)


class EnvioDePlanilhaForm(BootstrapFormMixin, forms.Form):
    """Envio de uma planilha (.xlsx) para importar: confere o arquivo e o lê com `ler`."""

    TAMANHO_MAXIMO_MB = 5

    arquivo = forms.FileField(
        label="Planilha (Excel)",
        validators=[FileExtensionValidator(["xlsx"])],
        help_text=f"Arquivo .xlsx de até {TAMANHO_MAXIMO_MB} MB.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["arquivo"].widget.attrs["accept"] = ".xlsx"

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if arquivo.size > self.TAMANHO_MAXIMO_MB * 1024 * 1024:
            raise ValidationError(f"O arquivo passa de {self.TAMANHO_MAXIMO_MB} MB.")
        try:
            self.ler(arquivo)
        except PlanilhaInvalidaError as erro:
            raise ValidationError(str(erro)) from erro
        return arquivo

    def ler(self, arquivo) -> None:
        """Lê a planilha e guarda o resultado no formulário; levanta PlanilhaInvalidaError."""
        raise NotImplementedError


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
            "data_nascimento": CampoData(),
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
