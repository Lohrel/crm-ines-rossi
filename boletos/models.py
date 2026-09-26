"""Boletos que a corretora envia aos clientes.

Serve para não esquecer de enviar: cada boleto fica "a enviar" até alguém
registrar o envio. O pagamento não é acompanhado aqui.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from apolices.models import Contrato
from clientes.models import Contato, Registro

# Quantos dias antes do vencimento o boleto não enviado passa a pedir atenção.
DIAS_DE_ANTECEDENCIA = 7
# A lista abre no que falta enviar com vencimento até esta quantidade de dias à frente.
DIAS_NA_LISTA = 30


def somar_meses(mes: date, quantos: int) -> date:
    """Dia 1º do mês que fica `quantos` meses depois."""
    indice = mes.year * 12 + mes.month - 1 + quantos
    return date(indice // 12, indice % 12 + 1, 1)


def meses_entre(de: date, ate: date) -> list[date]:
    """Dia 1º de cada mês, de `de` até `ate`, inclusive."""
    total = (ate.year - de.year) * 12 + ate.month - de.month
    return [somar_meses(de, n) for n in range(total + 1)]


class Situacao(models.TextChoices):
    A_ENVIAR = "enviar", "A enviar"
    ENVIADO = "enviado", "Enviado"
    CANCELADO = "cancelado", "Cancelado"


class BoletoQuerySet(models.QuerySet):
    def a_enviar(self):
        return self.filter(enviado_em__isnull=True, cancelado=False)

    def enviados(self):
        return self.filter(enviado_em__isnull=False, cancelado=False)

    def cancelados(self):
        return self.filter(cancelado=True)

    def na_situacao(self, situacao: str):
        filtros = {
            Situacao.A_ENVIAR: self.a_enviar,
            Situacao.ENVIADO: self.enviados,
            Situacao.CANCELADO: self.cancelados,
        }
        return filtros[situacao]()

    def vencidos(self, hoje: date):
        """Não enviados e já vencidos."""
        return self.a_enviar().filter(vencimento__lt=hoje)

    def vencendo(self, hoje: date, dias: int = DIAS_DE_ANTECEDENCIA):
        """Não enviados que vencem de hoje até os próximos dias."""
        return self.a_enviar().filter(vencimento__range=(hoje, hoje + timedelta(days=dias)))


class Boleto(Registro):
    class Tipo(models.TextChoices):
        MENSALIDADE = "MEN", "Mensalidade"
        COPARTICIPACAO = "COP", "Coparticipação"
        REAJUSTE = "REA", "Reajuste"
        ESPECIAL = "ESP", "Caso especial"

    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="boletos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.MENSALIDADE)
    # Guardado como o dia 1º do mês.
    referencia = models.DateField("mês de referência")
    vencimento = models.DateField(
        help_text="Se ficar em branco, usa o dia de vencimento do contrato no mês de referência."
    )
    fora_do_vencimento = models.BooleanField(
        "fora do vencimento",
        default=False,
        editable=False,
        help_text="Vencimento diferente do dia de vencimento do contrato.",
    )
    valor = models.DecimalField(
        "valor (R$)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    enviado_em = models.DateField("enviado em", null=True, blank=True)
    enviado_para = models.ForeignKey(
        Contato,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="boletos",
        verbose_name="enviado para",
    )
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="enviado por",
    )
    cancelado = models.BooleanField(
        default=False, help_text="Ex.: substituído por outro depois de uma negociação."
    )
    observacao = models.TextField("observação", blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    history = HistoricalRecords()
    objects = BoletoQuerySet.as_manager()

    class Meta:
        verbose_name = "boleto"
        verbose_name_plural = "boletos"
        ordering = ["vencimento", "contrato__cliente__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "referencia"],
                condition=Q(tipo="MEN", cancelado=False),
                name="boleto_uma_mensalidade_por_mes",
                violation_error_message="Este contrato já tem a mensalidade deste mês.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.referencia:%m/%Y} · {self.contrato.cliente}"

    def get_absolute_url(self) -> str:
        return reverse("boletos:detalhe", args=[self.pk])

    @property
    def vencimento_habitual(self) -> date:
        return self.contrato.vencimento_da_referencia(self.referencia)

    @property
    def situacao(self) -> Situacao:
        if self.cancelado:
            return Situacao.CANCELADO
        return Situacao.ENVIADO if self.enviado_em else Situacao.A_ENVIAR

    @property
    def dias_para_vencer(self) -> int | None:
        """Só para os que faltam enviar; negativo quando já venceu."""
        if self.situacao != Situacao.A_ENVIAR:
            return None
        return (self.vencimento - date.today()).days

    @property
    def pede_atencao(self) -> bool:
        """Falta enviar e vence nos próximos dias (ou já venceu)."""
        dias = self.dias_para_vencer
        return dias is not None and dias <= DIAS_DE_ANTECEDENCIA

    @property
    def prazo(self) -> str:
        """Prazo dos que faltam enviar, ex.: "vence em 3 dias" ou "venceu há 2 dias"."""
        dias = self.dias_para_vencer
        textos = {None: "", -1: "venceu ontem", 0: "vence hoje", 1: "vence amanhã"}
        if dias in textos:
            return textos[dias]
        return f"vence em {dias} dias" if dias > 0 else f"venceu há {-dias} dias"

    def validate_constraints(self, exclude=None) -> None:
        # Os formulários não mostram todos os campos da regra "uma mensalidade por mês"
        # (o contrato, na edição; "cancelado", no cadastro), e o Django pularia a regra.
        # Esses valores já estão no próprio boleto, então a regra é sempre conferida.
        exclude = set(exclude or ()) - {"contrato", "cancelado"}
        super().validate_constraints(exclude=exclude)

    def clean(self) -> None:
        super().clean()
        if self.referencia:
            self.referencia = self.referencia.replace(day=1)
        contato = self.enviado_para
        if contato and self.contrato_id and contato.cliente_id != self.contrato.cliente_id:
            raise ValidationError({"enviado_para": "O contato deve ser deste cliente."})

    def save(self, *args, **kwargs):
        self.referencia = self.referencia.replace(day=1)
        if self.vencimento is None:
            self.vencimento = self.vencimento_habitual
        self.fora_do_vencimento = self.vencimento != self.vencimento_habitual
        super().save(*args, **kwargs)

    def registrar_envio(self, usuario, em: date | None = None, para: Contato | None = None):
        if self.situacao != Situacao.A_ENVIAR:
            raise ValidationError(f"Este boleto já está {self.situacao.label.lower()}.")
        self.enviado_em = em or date.today()
        self.enviado_para = para
        self.enviado_por = usuario
        self.save()

    @classmethod
    def gerar_mensalidades(
        cls, de: date, ate: date | None = None, contrato: Contrato | None = None, usuario=None
    ) -> tuple[int, int]:
        """Cria as mensalidades de cada mês, de `de` até `ate`.

        Vale para os contratos vigentes em que a corretora envia o boleto, ou só para o
        contrato indicado. Não repete: pula o mês que o contrato já tem, mesmo com a
        mensalidade cancelada. Devolve quantos boletos criou e quantos já existiam.
        """
        meses = meses_entre(de, ate or de)
        criados = existentes = 0
        with transaction.atomic():
            # Trava os contratos: num clique duplo (ou duas pessoas ao mesmo tempo), a
            # segunda geração espera a primeira terminar e encontra tudo já criado.
            contratos = Contrato.objects.vigentes().com_boleto_da_corretora()
            if contrato is not None:
                contratos = contratos.filter(pk=contrato.pk)
            contratos = list(contratos.select_for_update())
            ja_tem = set(
                cls.objects.filter(tipo=cls.Tipo.MENSALIDADE, referencia__in=meses).values_list(
                    "contrato_id", "referencia"
                )
            )
            for referencia in meses:
                fim_do_mes = somar_meses(referencia, 1) - timedelta(days=1)
                for plano in contratos:
                    if plano.inicio_vigencia > fim_do_mes:
                        continue
                    if (plano.pk, referencia) in ja_tem:
                        existentes += 1
                        continue
                    cls.objects.create(
                        contrato=plano,
                        tipo=cls.Tipo.MENSALIDADE,
                        referencia=referencia,
                        vencimento=plano.vencimento_da_referencia(referencia),
                        registrado_por=usuario,
                    )
                    criados += 1
        return criados, existentes

    @classmethod
    def seguir_novo_vencimento(cls, contrato: Contrato) -> int:
        """O contrato mudou o dia de vencimento ou o pré/pós-pagamento.

        As mensalidades a enviar que ainda não venceram, e que estavam no vencimento de
        costume, passam para o novo. Devolve quantas mudaram.
        """
        mudaram = 0
        mensalidades = cls.objects.a_enviar().filter(
            contrato=contrato,
            tipo=cls.Tipo.MENSALIDADE,
            fora_do_vencimento=False,
            vencimento__gte=date.today(),
        )
        for boleto in mensalidades:
            boleto.contrato = contrato
            novo = contrato.vencimento_da_referencia(boleto.referencia)
            if boleto.vencimento != novo:
                boleto.vencimento = novo
                boleto.save()
                mudaram += 1
        return mudaram

    @classmethod
    def cancelar_com_o_contrato(cls, contrato: Contrato) -> int:
        """O contrato foi cancelado: cancela as mensalidades a enviar dos próximos meses.

        As do mês atual e anteriores ficam, porque ainda podem precisar ser enviadas
        (no pós-pagamento, a do último mês vence depois). Devolve quantas cancelou.
        """
        proximo_mes = somar_meses(date.today(), 1)
        mensalidades = cls.objects.a_enviar().filter(
            contrato=contrato, tipo=cls.Tipo.MENSALIDADE, referencia__gte=proximo_mes
        )
        canceladas = 0
        for boleto in mensalidades:
            boleto.cancelado = True
            nota = "Cancelado junto com o contrato."
            boleto.observacao = f"{boleto.observacao}\n{nota}".strip()
            boleto.save()
            canceladas += 1
        return canceladas
