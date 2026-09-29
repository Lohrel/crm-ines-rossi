"""Pendências do dia a dia: o que alguém da corretora precisa resolver até uma data.

Toda pendência é de um cliente e, nas empresas, de uma unidade (matriz ou
filial). Pode apontar também o contrato ou a movimentação a que se refere. Ao
concluir, ficam registrados quem concluiu e quando.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from apolices.models import Contrato
from clientes.models import Cliente, Registro, Unidade
from clientes.prazos import texto_do_prazo
from movimentacoes.models import Movimentacao

# Quantos dias antes do prazo a pendência em aberto passa a pedir atenção.
DIAS_DE_ANTECEDENCIA = 3


class PendenciaQuerySet(models.QuerySet):
    def para_tabela(self):
        """Já traz o que as tabelas de pendências mostram, sem uma consulta por linha."""
        return self.select_related(
            "cliente",
            "unidade",
            "responsavel",
            "concluida_por",
            "contrato__ramo",
            "contrato__seguradora",
            "movimentacao__beneficiario",
            "movimentacao__contrato__ramo",
        )

    def em_aberto(self):
        return self.filter(concluida_em__isnull=True)

    def concluidas(self):
        return self.filter(concluida_em__isnull=False)

    def vencidas(self, hoje: date):
        """Em aberto e com o prazo já passado."""
        return self.em_aberto().filter(prazo__lt=hoje)

    def vencendo(self, hoje: date, dias: int = DIAS_DE_ANTECEDENCIA):
        """Em aberto e com o prazo de hoje até os próximos dias."""
        return self.em_aberto().filter(prazo__range=(hoje, hoje + timedelta(days=dias)))

    def buscar(self, termo: str):
        termo = (termo or "").strip()
        if not termo:
            return self
        return self.filter(
            Q(descricao__icontains=termo)
            | Q(cliente__nome__icontains=termo)
            | Q(unidade__nome_fantasia__icontains=termo)
            | Q(unidade__razao_social__icontains=termo)
        )


class Pendencia(Registro):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pendencias")
    unidade = models.ForeignKey(
        Unidade,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pendencias",
        verbose_name="unidade (filial)",
        help_text="Nas empresas com filiais, a filial (ou a matriz) a que a pendência se refere.",
    )
    descricao = models.CharField(
        "descrição", max_length=200, help_text="Ex.: cobrar do RH a DPS do João."
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pendencias",
        verbose_name="responsável",
    )
    prazo = models.DateField()
    contrato = models.ForeignKey(
        Contrato, on_delete=models.PROTECT, null=True, blank=True, related_name="pendencias"
    )
    movimentacao = models.ForeignKey(
        Movimentacao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pendencias",
        verbose_name="movimentação",
    )
    observacao = models.TextField("observação", blank=True)
    concluida_em = models.DateField("concluída em", null=True, blank=True, editable=False)
    concluida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="concluída por",
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="registrada por",
    )

    history = HistoricalRecords()
    objects = PendenciaQuerySet.as_manager()

    class Meta:
        verbose_name = "pendência"
        verbose_name_plural = "pendências"
        ordering = ["prazo", "criado_em"]

    def __str__(self) -> str:
        return self.descricao

    def get_absolute_url(self) -> str:
        return reverse("pendencias:detalhe", args=[self.pk])

    @property
    def concluida(self) -> bool:
        return self.concluida_em is not None

    @property
    def dias_para_o_prazo(self) -> int | None:
        """Só para as em aberto; negativo quando o prazo já passou."""
        return None if self.concluida else (self.prazo - date.today()).days

    @property
    def pede_atencao(self) -> bool:
        """Em aberto e com o prazo nos próximos dias (ou já passado)."""
        dias = self.dias_para_o_prazo
        return dias is not None and dias <= DIAS_DE_ANTECEDENCIA

    @property
    def texto_do_prazo(self) -> str:
        dias = self.dias_para_o_prazo
        return "" if dias is None else texto_do_prazo(dias)

    def clean(self) -> None:
        super().clean()
        if not self.cliente_id:
            return
        if self.cliente.eh_empresa:
            if not self.unidade_id:
                self.unidade = self._unica_unidade_da_empresa()
        elif self.unidade_id:
            raise ValidationError({"unidade": "Pessoa física não tem filial."})
        erros = {}
        if self.unidade_id and self.unidade.cliente_id != self.cliente_id:
            erros["unidade"] = "A unidade deve ser deste cliente."
        if self.contrato_id and self.contrato.cliente_id != self.cliente_id:
            erros["contrato"] = "O contrato deve ser deste cliente."
        if self.movimentacao_id and self.movimentacao.cliente_id != self.cliente_id:
            erros["movimentacao"] = "A movimentação deve ser deste cliente."
        if erros:
            raise ValidationError(erros)

    def _unica_unidade_da_empresa(self) -> Unidade:
        """Empresa sem filiais: a pendência é da matriz. Com filiais, é preciso escolher."""
        unidades = list(self.cliente.unidades.all()[:2])
        if len(unidades) == 1:
            return unidades[0]
        if not unidades:
            raise ValidationError("Cadastre a matriz desta empresa antes de criar a pendência.")
        raise ValidationError({"unidade": "Informe a filial (ou a matriz) desta pendência."})

    def concluir(self, usuario, em: date | None = None) -> None:
        if self.concluida:
            raise ValidationError("Esta pendência já foi concluída.")
        self.concluida_em = em or date.today()
        self.concluida_por = usuario
        self.save()

    def reabrir(self) -> None:
        if not self.concluida:
            raise ValidationError("Esta pendência já está em aberto.")
        self.concluida_em = None
        self.concluida_por = None
        self.save()
