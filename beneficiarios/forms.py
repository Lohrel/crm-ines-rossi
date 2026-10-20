from datetime import date

from django import forms
from django.utils.text import capfirst

from apolices.forms import PlanoDoContratoField
from apolices.models import Contrato, Plano, Subfatura
from beneficiarios.importacao_de_vidas import ler_planilha
from beneficiarios.models import Anexo, Beneficiario, Vinculo
from clientes.documentos import CPF
from clientes.forms import BootstrapFormMixin, DocumentoField, EnvioDePlanilhaForm, MesField
from clientes.models import Cliente, Unidade
from clientes.widgets import CampoData

DATA = CampoData()
CAMPOS_PESSOAIS = ["nome", "cpf", "data_nascimento", "sexo", "nome_mae"]


class BeneficiarioFormBase(BootstrapFormMixin, forms.ModelForm):
    cpf = DocumentoField(CPF, required=False)

    class Meta:
        model = Beneficiario
        fields = CAMPOS_PESSOAIS
        widgets = {
            "data_nascimento": DATA,
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cpf"].widget.attrs.update(placeholder="000.000.000-00", inputmode="numeric")

    def clean_cpf(self):
        # Vazio vira NULL, para não colidir com outros beneficiários sem CPF.
        return self.cleaned_data["cpf"] or None


class TitularForm(BeneficiarioFormBase):
    class Meta(BeneficiarioFormBase.Meta):
        fields = [
            *CAMPOS_PESSOAIS,
            "unidade",
            "matricula",
            "telefone",
            "whatsapp",
            "email",
            "observacoes",
        ]

    def __init__(self, *args, cliente: Cliente | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if cliente is not None:
            self.instance.cliente = cliente
        cliente = self.instance.cliente
        if cliente.eh_empresa:
            self.fields["unidade"].queryset = cliente.unidades.all()
            self.fields["unidade"].required = True
        else:
            del self.fields["unidade"]
            del self.fields["matricula"]


class DependenteForm(BeneficiarioFormBase):
    class Meta(BeneficiarioFormBase.Meta):
        fields = [*CAMPOS_PESSOAIS, "parentesco", "observacoes"]

    def __init__(self, *args, titular: Beneficiario | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if titular is not None:
            self.instance.titular = titular
            self.instance.cliente = titular.cliente
        self.fields["parentesco"].required = True


class VinculoForm(BootstrapFormMixin, forms.ModelForm):
    """Inclusão num plano. Para o titular, permite incluir junto os dependentes escolhidos.

    Nos contratos com planos cadastrados (ex.: TNPQ e TNP4), escolhe-se o plano da pessoa.
    """

    dependentes = forms.ModelMultipleChoiceField(
        label="Incluir também os dependentes",
        queryset=Beneficiario.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Marque só os dependentes que entram neste plano. Eles entram no mesmo plano.",
    )

    class Meta:
        model = Vinculo
        fields = ["contrato", "plano", "carteirinha", "data_inclusao", "data_exclusao", "salario"]
        widgets = {"data_inclusao": DATA, "data_exclusao": DATA}

    def __init__(self, *args, beneficiario: Beneficiario | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if beneficiario is not None:
            self.instance.beneficiario = beneficiario
        pessoa = self.instance.beneficiario
        if self.instance.pk:
            self._preparar_edicao()
            usam_salario = self.instance.contrato.usa_salario
        else:
            contratos = list(self._contratos_possiveis(pessoa))
            self.fields["contrato"] = PlanoDoContratoField()
            self.fields["contrato"].definir(contratos)
            self.initial.setdefault("contrato", self._plano_do_titular(pessoa, contratos))
            del self.fields["plano"]
            del self.fields["data_exclusao"]
            self.initial.setdefault("data_inclusao", date.today())
            if pessoa.eh_titular and pessoa.dependentes.exists():
                self.fields["dependentes"].queryset = pessoa.dependentes.all()
            else:
                del self.fields["dependentes"]
            usam_salario = any(contrato.usa_salario for contrato in contratos)
        # O salário só aparece para o titular, quando há seguro de vida com capital pelo salário.
        if not (usam_salario and pessoa.eh_titular):
            del self.fields["salario"]

    def _preparar_edicao(self) -> None:
        del self.fields["dependentes"]
        contrato = self.instance.contrato
        self.fields["contrato"].queryset = Contrato.objects.filter(pk=contrato.pk)
        self.fields["contrato"].disabled = True
        # O plano dentro do contrato pode ser corrigido aqui; a troca pedida à operadora
        # é uma movimentação de alteração de plano.
        planos = Plano.objects.filter(contrato=contrato)
        if not planos.exists():
            del self.fields["plano"]
            return
        self.fields["plano"].queryset = planos.filter(ativo=True) | planos.filter(
            pk=self.instance.plano_id
        )
        self.fields["plano"].label = "Plano"
        self.fields["plano"].empty_label = "Ainda não informado"
        self.fields["plano"].help_text = (
            "Para corrigir o cadastro. A troca de plano pedida à operadora é feita pela "
            "movimentação de alteração de plano."
        )

    @staticmethod
    def _contratos_possiveis(pessoa: Beneficiario):
        contratos = Contrato.objects.de_pessoas().filter(cliente=pessoa.cliente)
        contratos = contratos.select_related("ramo", "seguradora").prefetch_related("planos")
        if not pessoa.eh_titular:
            contratos = contratos.filter(vinculos__in=pessoa.titular.vinculos.ativos()).distinct()
        return contratos

    @staticmethod
    def _plano_do_titular(pessoa: Beneficiario, contratos: list[Contrato]) -> str | None:
        """O dependente começa com o plano do titular marcado (se ele estiver num só)."""
        if pessoa.eh_titular:
            return None
        planos = list(pessoa.titular.vinculos.ativos().filter(contrato__in=contratos))
        if len(planos) != 1:
            return None
        return PlanoDoContratoField.valor(planos[0].contrato, planos[0].plano)

    def clean(self):
        dados = super().clean()
        escolha = dados.get("contrato")
        if isinstance(escolha, tuple):
            contrato, self.instance.plano = escolha
            dados["contrato"] = contrato
        contrato = dados.get("contrato")
        if contrato and not contrato.usa_salario and dados.get("salario") is not None:
            # Salário digitado para um plano que não é seguro de vida: não é guardado.
            dados["salario"] = None
        for dependente in dados.get("dependentes") or []:
            if dependente.vinculos.filter(contrato=contrato, data_exclusao__isnull=True).exists():
                self.add_error("dependentes", f"{dependente} já está neste plano.")
        return dados

    def save(self, commit=True):
        vinculo = super().save(commit)
        if commit:
            for dependente in self.cleaned_data.get("dependentes") or []:
                # Mesmo cliente e unidade do titular: as regras já valem pelo plano dele.
                Vinculo.objects.create(
                    beneficiario=dependente,
                    contrato=vinculo.contrato,
                    plano=vinculo.plano,
                    data_inclusao=vinculo.data_inclusao,
                )
        return vinculo


class EncerrarVinculoForm(BootstrapFormMixin, forms.Form):
    data_exclusao = forms.DateField(label="Data de exclusão", widget=DATA)

    def __init__(self, *args, vinculo: Vinculo, **kwargs):
        super().__init__(*args, **kwargs)
        self.vinculo = vinculo
        self.initial.setdefault("data_exclusao", date.today())

    def clean_data_exclusao(self):
        data = self.cleaned_data["data_exclusao"]
        if data < self.vinculo.data_inclusao:
            raise forms.ValidationError("A exclusão não pode ser antes da inclusão.")
        return data


class AnexoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["tipo", "descricao", "arquivo"]
        widgets = {"arquivo": forms.FileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"})}

    def __init__(self, *args, beneficiario: Beneficiario | None = None, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if beneficiario is not None:
            self.instance.beneficiario = beneficiario
        self.instance.enviado_por = usuario

    def save(self, commit=True):
        self.instance.nome_original = self.cleaned_data["arquivo"].name[:255]
        return super().save(commit)


class BuscaBeneficiarioForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(label="Buscar", required=False)
    contrato = forms.ModelChoiceField(
        queryset=Contrato.objects.none(), required=False, empty_label="Todos os planos"
    )
    unidade = forms.ModelChoiceField(
        queryset=Unidade.objects.none(), required=False, empty_label="Todas as unidades"
    )
    inativos = forms.BooleanField(label="Mostrar quem saiu de todos os planos", required=False)

    def __init__(self, *args, cliente: Cliente, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Nome, CPF, matrícula ou carteirinha"
        self.fields["contrato"].queryset = cliente.contratos.de_pessoas().select_related(
            "seguradora", "ramo"
        )
        if cliente.eh_empresa:
            self.fields["unidade"].queryset = cliente.unidades.all()
        else:
            del self.fields["unidade"]


class MesDaPlanilhaForm(BootstrapFormMixin, forms.Form):
    mes = MesField(label="Mês da planilha")


class SubfaturaForm(BootstrapFormMixin, forms.ModelForm):
    """Local e subfatura de uma filial no contrato, como a seguradora a identifica."""

    class Meta:
        model = Subfatura
        fields = ["local", "identificador", "boleto_separado"]

    def __init__(self, *args, filial=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Na tabela das filiais não há rótulo em cada campo: o nome diz de qual filial ele é.
        if filial is not None:
            for campo in self.fields.values():
                campo.widget.attrs["aria-label"] = f"{capfirst(campo.label)} de {filial}"


class ImportacaoDeVidasForm(EnvioDePlanilhaForm):
    """Arquivo da planilha do seguro de vida a importar."""

    def ler(self, arquivo) -> None:
        self.planilha = ler_planilha(arquivo)


class EntradaDasVidasNovasForm(BootstrapFormMixin, forms.Form):
    entrada = forms.DateField(
        label="Quem ainda não está no plano entra em",
        widget=DATA,
        help_text="Em geral, a data da planilha.",
    )
