from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from clientes.documentos import CNPJ
from clientes.models import Cliente, Registro, Unidade
from clientes.validators import validar_cnpj


class Seguradora(Registro):
    nome = models.CharField(max_length=150, unique=True)
    # null (e não texto vazio) para que várias seguradoras sem CNPJ não violem a unicidade.
    cnpj = models.CharField(  # noqa: DJ001
        "CNPJ", max_length=14, null=True, blank=True, unique=True, validators=[validar_cnpj]
    )
    telefone = models.CharField("telefone de atendimento", max_length=30, blank=True)
    site = models.URLField(blank=True)
    ativo = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome

    def get_absolute_url(self) -> str:
        return reverse("apolices:seguradoras")

    @property
    def cnpj_formatado(self) -> str:
        return CNPJ(self.cnpj).formatado() if self.cnpj else ""


class Ramo(models.Model):
    """Ramo do seguro: vida, saúde, dental, auto, imóvel..."""

    nome = models.CharField(max_length=60, unique=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome


class ContratoQuerySet(models.QuerySet):
    def vigentes(self):
        return self.filter(situacao__in=Contrato.SITUACOES_VIGENTES)

    def com_boleto_da_corretora(self):
        return self.filter(corretora_envia_boleto=True)

    def renovam_ate(self, data: date):
        return self.vigentes().filter(data_renovacao__lte=data)


class Contrato(Registro):
    """Apólice ou contrato de um cliente com uma seguradora.

    Uma empresa pode ter vários contratos; cada um indica quais unidades
    (matriz/filiais) ele cobre.
    """

    class Modalidade(models.TextChoices):
        INDIVIDUAL = "IF", "Individual/familiar"
        EMPRESARIAL = "EM", "Empresarial"

    class Situacao(models.TextChoices):
        IMPLANTACAO = "IMP", "Em implantação"
        ATIVO = "ATV", "Ativo"
        SUSPENSO = "SUS", "Suspenso"
        CANCELADO = "CAN", "Cancelado"

    SITUACOES_VIGENTES = [Situacao.IMPLANTACAO, Situacao.ATIVO, Situacao.SUSPENSO]

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="contratos")
    seguradora = models.ForeignKey(Seguradora, on_delete=models.PROTECT, related_name="contratos")
    ramo = models.ForeignKey(Ramo, on_delete=models.PROTECT, related_name="contratos")
    numero = models.CharField("número da apólice/contrato", max_length=60)
    produto = models.CharField("produto/plano", max_length=150, blank=True)
    modalidade = models.CharField(max_length=2, choices=Modalidade.choices)
    situacao = models.CharField(
        "situação", max_length=3, choices=Situacao.choices, default=Situacao.ATIVO
    )
    inicio_vigencia = models.DateField("início da vigência")
    data_renovacao = models.DateField("data de renovação", null=True, blank=True)
    dia_vencimento = models.PositiveSmallIntegerField(
        "dia de vencimento da fatura",
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    dia_fechamento = models.PositiveSmallIntegerField(
        "dia de fechamento das movimentações",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text=(
            "Último dia do mês para enviar movimentações com vigência no dia 1º do mês "
            "seguinte (ex.: 25, fechamento do portal da operadora)."
        ),
    )
    valor_mensal = models.DecimalField(
        "valor mensal (R$)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    corretora_envia_boleto = models.BooleanField("a corretora envia o boleto", default=False)
    coparticipacao = models.BooleanField("tem coparticipação", default=False)
    unidades = models.ManyToManyField(
        Unidade,
        verbose_name="unidades cobertas",
        related_name="contratos",
        blank=True,
        help_text="Matriz e filiais que este contrato cobre.",
    )
    observacoes = models.TextField("observações", blank=True)

    history = HistoricalRecords(m2m_fields=[unidades])
    objects = ContratoQuerySet.as_manager()

    class Meta:
        verbose_name = "contrato"
        ordering = ["cliente__nome", "seguradora__nome", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["seguradora", "numero"],
                name="contrato_numero_unico_por_seguradora",
                violation_error_message="Já existe um contrato com este número nesta seguradora.",
            ),
            models.CheckConstraint(
                condition=Q(data_renovacao__isnull=True)
                | Q(data_renovacao__gte=models.F("inicio_vigencia")),
                name="contrato_renovacao_apos_inicio",
                violation_error_message="A renovação não pode ser antes do início da vigência.",
            ),
            models.CheckConstraint(
                condition=Q(dia_vencimento__gte=1, dia_vencimento__lte=31),
                name="contrato_dia_vencimento_valido",
                violation_error_message="O dia de vencimento deve estar entre 1 e 31.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.seguradora} {self.numero}"

    def get_absolute_url(self) -> str:
        return self.cliente.get_absolute_url()

    def vigencia_sugerida(self, recebida_em: date) -> date:
        """Dia 1º do mês seguinte; depois do fechamento, dia 1º do outro mês."""
        meses = 1
        if self.dia_fechamento and recebida_em.day > self.dia_fechamento:
            meses = 2
        indice = recebida_em.month - 1 + meses
        return date(recebida_em.year + indice // 12, indice % 12 + 1, 1)

    @property
    def vigente(self) -> bool:
        return self.situacao in self.SITUACOES_VIGENTES

    def clean(self) -> None:
        super().clean()
        if (
            self.modalidade == self.Modalidade.EMPRESARIAL
            and self.cliente_id
            and not self.cliente.eh_empresa
        ):
            raise ValidationError(
                {"modalidade": "Contrato empresarial precisa ser de um cliente pessoa jurídica."}
            )

    def validar_unidades(self, unidades: list[Unidade]) -> None:
        """Só aceita unidades da própria empresa do contrato."""
        de_outro_cliente = [u for u in unidades if u.cliente_id != self.cliente_id]
        if de_outro_cliente:
            raise ValidationError(
                {"unidades": "Todas as unidades devem ser da empresa deste contrato."}
            )
