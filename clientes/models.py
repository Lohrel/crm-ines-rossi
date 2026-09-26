import re

from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from clientes.documentos import CNPJ, CPF
from clientes.validators import validar_cnpj, validar_cpf


class UF(models.TextChoices):
    AC = "AC", "Acre"
    AL = "AL", "Alagoas"
    AP = "AP", "Amapá"
    AM = "AM", "Amazonas"
    BA = "BA", "Bahia"
    CE = "CE", "Ceará"
    DF = "DF", "Distrito Federal"
    ES = "ES", "Espírito Santo"
    GO = "GO", "Goiás"
    MA = "MA", "Maranhão"
    MT = "MT", "Mato Grosso"
    MS = "MS", "Mato Grosso do Sul"
    MG = "MG", "Minas Gerais"
    PA = "PA", "Pará"
    PB = "PB", "Paraíba"
    PR = "PR", "Paraná"
    PE = "PE", "Pernambuco"
    PI = "PI", "Piauí"
    RJ = "RJ", "Rio de Janeiro"
    RN = "RN", "Rio Grande do Norte"
    RS = "RS", "Rio Grande do Sul"
    RO = "RO", "Rondônia"
    RR = "RR", "Roraima"
    SC = "SC", "Santa Catarina"
    SP = "SP", "São Paulo"
    SE = "SE", "Sergipe"
    TO = "TO", "Tocantins"


class Endereco(models.Model):
    """Campos de endereço reutilizados por pessoa física e por unidade de empresa."""

    cep = models.CharField("CEP", max_length=9, blank=True)
    logradouro = models.CharField("rua", max_length=200, blank=True)
    numero = models.CharField("número", max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, choices=UF.choices, blank=True)

    class Meta:
        abstract = True

    @property
    def endereco_resumido(self) -> str:
        rua = ", ".join(p for p in [self.logradouro, self.numero] if p)
        local = " / ".join(p for p in [self.cidade, self.uf] if p)
        return " · ".join(p for p in [rua, self.bairro, local] if p)


class MeiosDeContato(models.Model):
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    email = models.EmailField("e-mail", blank=True)

    class Meta:
        abstract = True


class Registro(models.Model):
    """Datas de criação e alteração, comuns a todos os cadastros."""

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class MarcacaoExclusiva(models.Model):
    """Garante que só um registro do grupo fique marcado (ex.: uma matriz por empresa).

    Ao marcar um registro, o que estava marcado antes é desmarcado automaticamente.
    """

    campo_exclusivo: str
    campo_grupo: str

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if getattr(self, self.campo_exclusivo):
            with transaction.atomic():
                outros = (
                    type(self)
                    .objects.filter(
                        **{
                            self.campo_grupo: getattr(self, self.campo_grupo),
                            self.campo_exclusivo: True,
                        }
                    )
                    .exclude(pk=self.pk)
                )
                for outro in outros:
                    setattr(outro, self.campo_exclusivo, False)
                    outro.save(update_fields=[self.campo_exclusivo, "atualizado_em"])
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class ClienteQuerySet(models.QuerySet):
    def pessoas_fisicas(self):
        return self.filter(tipo=Cliente.Tipo.PESSOA_FISICA)

    def empresas(self):
        return self.filter(tipo=Cliente.Tipo.PESSOA_JURIDICA)

    def buscar(self, termo: str):
        """Busca por nome, CPF, CNPJ, razão social ou nome fantasia de qualquer unidade."""
        termo = (termo or "").strip()
        if not termo:
            return self
        filtro = (
            Q(nome__icontains=termo)
            | Q(unidades__razao_social__icontains=termo)
            | Q(unidades__nome_fantasia__icontains=termo)
        )
        digitos = re.sub(r"\D", "", termo)
        if len(digitos) >= 3:
            filtro |= Q(cpf__contains=digitos) | Q(unidades__cnpj__contains=digitos)
        return self.filter(filtro).distinct()


class Cliente(Endereco, MeiosDeContato, Registro):
    """Cliente da corretora: pessoa física ou empresa.

    Empresas (pessoa jurídica) podem ter várias unidades, cada uma com o
    próprio CNPJ e os próprios contatos. Os dados pessoais (CPF, nascimento,
    endereço e contato direto) só são usados para pessoa física.
    """

    class Tipo(models.TextChoices):
        PESSOA_FISICA = "PF", "Pessoa física"
        PESSOA_JURIDICA = "PJ", "Pessoa jurídica"

    class Sexo(models.TextChoices):
        FEMININO = "F", "Feminino"
        MASCULINO = "M", "Masculino"

    tipo = models.CharField(max_length=2, choices=Tipo.choices)
    nome = models.CharField(
        max_length=200, help_text="Nome da pessoa ou nome da empresa/grupo empresarial."
    )
    # null (e não texto vazio) para que várias empresas sem CPF não violem a unicidade.
    cpf = models.CharField(  # noqa: DJ001
        "CPF", max_length=11, null=True, blank=True, validators=[validar_cpf]
    )
    data_nascimento = models.DateField("data de nascimento", null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=Sexo.choices, blank=True)
    observacoes = models.TextField("observações", blank=True)
    ativo = models.BooleanField(default=True)

    history = HistoricalRecords()
    objects = ClienteQuerySet.as_manager()

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["cpf"],
                condition=Q(cpf__isnull=False),
                name="cliente_cpf_unico",
                violation_error_message="Já existe um cliente com este CPF.",
            ),
            models.CheckConstraint(
                condition=Q(tipo="PJ") | Q(tipo="PF", cpf__isnull=False),
                name="cliente_pf_tem_cpf",
                violation_error_message="Pessoa física precisa de CPF.",
            ),
            models.CheckConstraint(
                condition=Q(tipo="PF") | Q(tipo="PJ", cpf__isnull=True),
                name="cliente_pj_sem_cpf",
                violation_error_message="Empresa não tem CPF; use o CNPJ das unidades.",
            ),
        ]

    def __str__(self) -> str:
        return self.nome

    def get_absolute_url(self) -> str:
        return reverse("clientes:detalhe", args=[self.pk])

    @property
    def eh_empresa(self) -> bool:
        return self.tipo == self.Tipo.PESSOA_JURIDICA

    @property
    def cpf_formatado(self) -> str:
        return CPF(self.cpf).formatado() if self.cpf else ""

    @property
    def documento_principal(self) -> str:
        """CPF da pessoa ou CNPJ da matriz (ou da primeira unidade) da empresa."""
        if not self.eh_empresa:
            return self.cpf_formatado
        # Usa .all() para aproveitar unidades já carregadas (prefetch) na listagem.
        unidades = sorted(self.unidades.all(), key=lambda u: (not u.matriz, u.pk))
        return unidades[0].cnpj_formatado if unidades else ""


class Unidade(MarcacaoExclusiva, Endereco, MeiosDeContato, Registro):
    """Matriz ou filial de uma empresa cliente, com CNPJ próprio."""

    campo_exclusivo = "matriz"
    campo_grupo = "cliente"

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="unidades",
        limit_choices_to={"tipo": Cliente.Tipo.PESSOA_JURIDICA},
    )
    cnpj = models.CharField("CNPJ", max_length=14, unique=True, validators=[validar_cnpj])
    razao_social = models.CharField("razão social", max_length=200)
    nome_fantasia = models.CharField("nome fantasia", max_length=200, blank=True)
    matriz = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-matriz", "nome_fantasia", "razao_social"]
        constraints = [
            models.UniqueConstraint(
                fields=["cliente"],
                condition=Q(matriz=True),
                name="unidade_uma_matriz_por_cliente",
                violation_error_message="Esta empresa já tem uma matriz.",
            ),
        ]

    def __str__(self) -> str:
        return self.nome_fantasia or self.razao_social

    def get_absolute_url(self) -> str:
        return self.cliente.get_absolute_url()

    @property
    def cnpj_formatado(self) -> str:
        return CNPJ(self.cnpj).formatado()


class Contato(MarcacaoExclusiva, MeiosDeContato, Registro):
    """Pessoa de contato numa unidade (ex.: RH da filial)."""

    campo_exclusivo = "principal"
    campo_grupo = "unidade"

    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, related_name="contatos")
    nome = models.CharField(max_length=200)
    cargo = models.CharField("cargo/setor", max_length=100, blank=True)
    principal = models.BooleanField(
        default=False, help_text="Contato procurado primeiro nesta unidade."
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ["-principal", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["unidade"],
                condition=Q(principal=True),
                name="contato_um_principal_por_unidade",
                violation_error_message="Esta unidade já tem um contato principal.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.cargo})" if self.cargo else self.nome

    def get_absolute_url(self) -> str:
        return self.unidade.get_absolute_url()
