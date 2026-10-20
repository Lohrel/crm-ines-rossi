from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from apolices.models import Contrato, Plano
from clientes.documentos import CPF
from clientes.models import Cliente, ExclusaoProtegida, MeiosDeContato, Registro, Unidade
from clientes.validators import validar_cpf


class BeneficiarioQuerySet(models.QuerySet):
    def titulares(self):
        return self.filter(titular__isnull=True)

    def dependentes(self):
        return self.filter(titular__isnull=False)

    def buscar(self, termo: str):
        termo = (termo or "").strip()
        if not termo:
            return self
        filtro = Q(nome__icontains=termo) | Q(matricula__iexact=termo)
        filtro |= Q(vinculos__carteirinha__iexact=termo)
        if len(digitos := CPF(termo).valor) >= 3:
            filtro |= Q(cpf__contains=digitos)
        return self.filter(filtro).distinct()


class Beneficiario(ExclusaoProtegida, MeiosDeContato, Registro):
    """Titular ou dependente de um cliente.

    Os planos em que a pessoa está ficam em `Vinculo`: um titular pode estar
    em vários contratos (ex.: saúde e dental) e cada dependente só nos que
    forem escolhidos para ele. A unidade (filial) é a do titular.
    """

    class Parentesco(models.TextChoices):
        CONJUGE = "CJ", "Cônjuge/companheiro(a)"
        FILHO = "FI", "Filho(a)"
        ENTEADO = "EN", "Enteado(a)"
        PAI_MAE = "PM", "Pai/mãe"
        OUTRO = "OU", "Outro"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="beneficiarios")
    titular = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dependentes",
    )
    parentesco = models.CharField(max_length=2, choices=Parentesco.choices, blank=True)
    unidade = models.ForeignKey(
        Unidade,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="beneficiarios",
        verbose_name="unidade (filial)",
        help_text="Unidade onde o titular trabalha. Os dependentes seguem a do titular.",
    )
    nome = models.CharField(max_length=200)
    # null (e não texto vazio) para que vários beneficiários sem CPF não violem a unicidade.
    cpf = models.CharField(  # noqa: DJ001
        "CPF", max_length=11, null=True, blank=True, validators=[validar_cpf]
    )
    data_nascimento = models.DateField("data de nascimento", null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=Cliente.Sexo.choices, blank=True)
    nome_mae = models.CharField("nome da mãe", max_length=200, blank=True)
    matricula = models.CharField("matrícula na empresa", max_length=50, blank=True)
    observacoes = models.TextField("observações", blank=True)

    history = HistoricalRecords()
    objects = BeneficiarioQuerySet.as_manager()

    dependentes_proprios = ("vinculos", "anexos")

    class Meta:
        verbose_name = "beneficiário"
        verbose_name_plural = "beneficiários"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["cliente", "cpf"],
                condition=Q(cpf__isnull=False),
                name="beneficiario_cpf_unico_por_cliente",
                violation_error_message="Já existe um beneficiário com este CPF neste cliente.",
            ),
            models.CheckConstraint(
                condition=Q(titular__isnull=True, parentesco="")
                | Q(titular__isnull=False, unidade__isnull=True) & ~Q(parentesco=""),
                name="beneficiario_parentesco_so_de_dependente",
                violation_error_message=(
                    "Dependente precisa de parentesco e segue a unidade do titular."
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.nome

    def get_absolute_url(self) -> str:
        return reverse("beneficiarios:detalhe", args=[self.pk])

    @property
    def eh_titular(self) -> bool:
        return self.titular_id is None

    @property
    def unidade_efetiva(self) -> Unidade | None:
        return self.unidade if self.eh_titular else self.titular.unidade

    @property
    def matricula_efetiva(self) -> str:
        """Matrícula do titular na empresa (o dependente usa a do titular)."""
        return self.matricula if self.eh_titular else self.titular.matricula

    @property
    def cpf_formatado(self) -> str:
        return CPF(self.cpf).formatado() if self.cpf else ""

    def excluir(self) -> None:
        """Exclui a pessoa com os planos e anexos (inclusive os arquivos do disco)."""
        arquivos = [anexo.arquivo for anexo in self.anexos.all()]
        with transaction.atomic():
            super().excluir()
            for arquivo in arquivos:
                transaction.on_commit(lambda a=arquivo: a.storage.delete(a.name))

    def planos_ativos(self, em: date | None = None):
        return self.vinculos.ativos(em).select_related("contrato__seguradora", "contrato__ramo")

    def clean(self) -> None:
        super().clean()
        if self.titular_id:
            if self.titular.titular_id:
                raise ValidationError("O titular escolhido é dependente de outra pessoa.")
            if self.titular.cliente_id != self.cliente_id:
                raise ValidationError("O dependente deve ser do mesmo cliente do titular.")
        elif self.cliente_id and self.cliente.eh_empresa and not self.unidade_id:
            raise ValidationError({"unidade": "Informe em qual unidade o titular trabalha."})
        if self.unidade_id and self.unidade.cliente_id != self.cliente_id:
            raise ValidationError({"unidade": "A unidade deve ser da empresa do beneficiário."})


class VinculoQuerySet(models.QuerySet):
    def ativos(self, em: date | None = None):
        """Planos em vigor na data (hoje, se não informada): são as "vidas"."""
        em = em or date.today()
        return self.filter(
            Q(data_exclusao__isnull=True) | Q(data_exclusao__gt=em), data_inclusao__lte=em
        )


class Vinculo(Registro):
    """Participação de um beneficiário num contrato (plano), com inclusão e exclusão."""

    beneficiario = models.ForeignKey(
        Beneficiario, on_delete=models.CASCADE, related_name="vinculos"
    )
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="vinculos")
    plano = models.ForeignKey(
        Plano,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vinculos",
        verbose_name="plano do contrato",
        help_text="Só nos contratos com mais de um plano (ex.: TNPQ ou TNP4).",
    )
    carteirinha = models.CharField("número da carteirinha", max_length=60, blank=True)
    data_inclusao = models.DateField("data de inclusão")
    data_exclusao = models.DateField(
        "data de exclusão",
        null=True,
        blank=True,
        help_text="A partir desta data a pessoa deixa de contar como vida no plano.",
    )
    salario = models.DecimalField(
        "salário (R$)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Só no seguro de vida, para calcular o capital. Pode ficar em branco.",
    )

    history = HistoricalRecords()
    objects = VinculoQuerySet.as_manager()

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["contrato__ramo__nome", "-data_inclusao"]
        constraints = [
            models.CheckConstraint(
                condition=Q(data_exclusao__isnull=True)
                | Q(data_exclusao__gte=models.F("data_inclusao")),
                name="vinculo_exclusao_apos_inclusao",
                violation_error_message="A exclusão não pode ser antes da inclusão.",
            ),
            models.UniqueConstraint(
                fields=["beneficiario", "contrato"],
                condition=Q(data_exclusao__isnull=True),
                name="vinculo_um_ativo_por_contrato",
                violation_error_message="Este beneficiário já está neste plano.",
            ),
        ]

    def __str__(self) -> str:
        texto = f"{self.contrato.ramo} · {self.contrato}"
        return f"{texto} · {self.plano}" if self.plano_id else texto

    def get_absolute_url(self) -> str:
        return self.beneficiario.get_absolute_url()

    @property
    def nome_do_plano(self) -> str:
        """O plano da pessoa dentro do contrato; sem ele, o nome do contrato (ex.: PLENO)."""
        return self.plano.nome if self.plano_id else self.contrato.nome_do_plano

    @property
    def falta_o_plano(self) -> bool:
        """Contrato com planos cadastrados em que ainda não se escolheu o plano da pessoa."""
        return self.plano_id is None and self.contrato.tem_planos

    @property
    def ativo(self) -> bool:
        hoje = date.today()
        return self.data_inclusao <= hoje and (
            self.data_exclusao is None or self.data_exclusao > hoje
        )

    @property
    def capital(self) -> Decimal | None:
        """Capital segurado no seguro de vida (sem salário, fica em branco)."""
        return self.contrato.capital_de(self.salario)

    @property
    def fatura(self) -> Decimal | None:
        return self.contrato.fatura_de(self.capital)

    def clean(self) -> None:
        super().clean()
        if not (self.beneficiario_id and self.contrato_id):
            return
        pessoa = self.beneficiario
        if self.contrato.cliente_id != pessoa.cliente_id:
            raise ValidationError({"contrato": "O contrato deve ser do mesmo cliente."})
        if self.plano_id and self.plano.contrato_id != self.contrato_id:
            raise ValidationError({"contrato": "O plano escolhido é de outro contrato."})
        unidade = pessoa.unidade_efetiva
        cobertas = list(self.contrato.unidades.all())
        if unidade and cobertas and unidade not in cobertas:
            raise ValidationError(
                {"contrato": f"Este contrato não cobre a unidade {unidade}. Ajuste o contrato."}
            )
        if not pessoa.eh_titular and self.data_inclusao:
            titular_no_plano = pessoa.titular.vinculos.filter(contrato=self.contrato).ativos(
                self.data_inclusao
            )
            if not titular_no_plano.exists():
                raise ValidationError(
                    {"contrato": "O titular não está neste plano na data de inclusão."}
                )

    def encerrar(self, data: date, so_do_mesmo_plano: bool = False) -> list["Vinculo"]:
        """Registra a exclusão do plano. Do titular, leva junto os dependentes do contrato.

        Com `so_do_mesmo_plano` (troca de plano dentro do contrato), só os dependentes que
        estão no mesmo plano do titular; os que estão em outro plano ficam onde estão.
        """
        encerrados = [self]
        with transaction.atomic():
            if self.beneficiario.eh_titular:
                dependentes = Vinculo.objects.filter(
                    beneficiario__titular=self.beneficiario,
                    contrato=self.contrato,
                    data_exclusao__isnull=True,
                )
                if so_do_mesmo_plano:
                    dependentes = dependentes.filter(plano=self.plano_id)
                encerrados += list(dependentes)
            for vinculo in encerrados:
                vinculo.data_exclusao = max(data, vinculo.data_inclusao)
                vinculo.save(update_fields=["data_exclusao", "atualizado_em"])
        return encerrados


def _caminho_do_anexo(anexo: "Anexo", nome_original: str) -> str:
    # Nome aleatório no disco: o nome original (que pode ter dados pessoais) fica só no banco.
    extensao = Path(nome_original).suffix.lower()
    return f"beneficiarios/{anexo.beneficiario_id}/{uuid4().hex}{extensao}"


def validar_tamanho_do_anexo(arquivo) -> None:
    limite = settings.TAMANHO_MAXIMO_ANEXO_MB
    if arquivo.size > limite * 1024 * 1024:
        raise ValidationError(f"O arquivo passa de {limite} MB.")


class Anexo(ExclusaoProtegida, Registro):
    """Arquivo de um beneficiário (DPS, eSocial, documentos). Pode conter dados de saúde."""

    EXTENSOES = ["pdf", "jpg", "jpeg", "png", "doc", "docx"]

    class Tipo(models.TextChoices):
        DPS = "DPS", "DPS (declaração de saúde)"
        ESOCIAL = "ESO", "eSocial"
        DOCUMENTO = "DOC", "Documento pessoal"
        COMPROVANTE = "CMP", "Comprovante (residência, vínculo etc.)"
        OUTRO = "OUT", "Outro"

    beneficiario = models.ForeignKey(Beneficiario, on_delete=models.CASCADE, related_name="anexos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    descricao = models.CharField("descrição", max_length=200, blank=True)
    arquivo = models.FileField(
        upload_to=_caminho_do_anexo,
        max_length=200,
        validators=[FileExtensionValidator(EXTENSOES), validar_tamanho_do_anexo],
        help_text=f"PDF, imagem ou Word, até {settings.TAMANHO_MAXIMO_ANEXO_MB} MB.",
    )
    nome_original = models.CharField("nome do arquivo", max_length=255, editable=False)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        editable=False,
        related_name="+",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "anexo"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return self.descricao or f"{self.get_tipo_display()}: {self.nome_original}"

    def get_absolute_url(self) -> str:
        return self.beneficiario.get_absolute_url()

    def excluir(self) -> None:
        """Apaga o registro e o arquivo do disco."""
        arquivo = self.arquivo
        with transaction.atomic():
            super().excluir()
            transaction.on_commit(lambda: arquivo.storage.delete(arquivo.name))
