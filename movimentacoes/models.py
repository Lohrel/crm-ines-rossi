"""Movimentações: pedidos de inclusão e exclusão enviados às operadoras.

O pedido só é registrado depois de enviado à operadora, então já começa em
análise. Quando a operadora aprova, a pessoa entra no plano (ou sai dele) a
partir da data de vigência, e só então passa a contar (ou deixa de contar)
como vida.
"""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from apolices.models import Contrato
from beneficiarios.models import Beneficiario, Vinculo
from clientes.models import Contato, Registro


class Etapa(models.TextChoices):
    EM_ANALISE = "ANA", "Em análise"
    APROVADA = "APR", "Aprovada"
    CONCLUIDA = "CON", "Concluída"
    REJEITADA = "REJ", "Rejeitada"
    CANCELADA = "CAN", "Cancelada"


ETAPAS_EM_ABERTO = [Etapa.EM_ANALISE, Etapa.APROVADA]

# Para onde cada etapa pode ir.
PROXIMAS_ETAPAS = {
    Etapa.EM_ANALISE: [Etapa.APROVADA, Etapa.REJEITADA, Etapa.CANCELADA],
    Etapa.APROVADA: [Etapa.CONCLUIDA],
    Etapa.CONCLUIDA: [],
    Etapa.REJEITADA: [],
    Etapa.CANCELADA: [],
}


class MovimentacaoQuerySet(models.QuerySet):
    def em_aberto(self):
        return self.filter(etapa__in=ETAPAS_EM_ABERTO)

    def com_vigencia_no_mes(self, ano: int, mes: int):
        return self.filter(vigencia__year=ano, vigencia__month=mes)

    def buscar(self, termo: str):
        termo = (termo or "").strip()
        if not termo:
            return self
        return self.filter(
            Q(beneficiario__nome__icontains=termo)
            | Q(beneficiario__matricula__iexact=termo)
            | Q(beneficiario__titular__matricula__iexact=termo)
            | Q(carteirinha__iexact=termo)
            | Q(cliente__nome__icontains=termo)
        )


class Movimentacao(Registro):
    class Tipo(models.TextChoices):
        INCLUSAO = "INC", "Inclusão"
        EXCLUSAO = "EXC", "Exclusão"

    class Motivo(models.TextChoices):
        RASURA = "RAS", "Rasura ou erro no formulário"
        ENTREVISTA = "ENT", "Prazo da entrevista médica"
        DOCUMENTOS = "DOC", "Documentação incompleta"
        OUTRO = "OUT", "Outro"

    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    # Repete o cliente da pessoa, para filtrar e listar por empresa sem juntar tabelas.
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="movimentacoes"
    )
    beneficiario = models.ForeignKey(
        Beneficiario, on_delete=models.PROTECT, related_name="movimentacoes"
    )
    contrato = models.ForeignKey(
        Contrato, on_delete=models.PROTECT, related_name="movimentacoes", verbose_name="plano"
    )
    solicitante = models.ForeignKey(
        Contato,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes",
        help_text="Quem pediu (ex.: o RH da filial).",
    )
    etapa = models.CharField(max_length=3, choices=Etapa.choices, default=Etapa.EM_ANALISE)
    recebida_em = models.DateField("recebida em", default=date.today)
    enviada_em = models.DateField("enviada à operadora em", null=True, blank=True)
    vigencia = models.DateField(
        "início de vigência (ou data da exclusão)",
        help_text="Se ficar em branco, usa o dia 1º do mês seguinte, conforme o fechamento.",
    )
    carteirinha = models.CharField("número da carteirinha", max_length=60, blank=True)
    carteirinha_enviada_em = models.DateField("carteirinha enviada em", null=True, blank=True)
    motivo_rejeicao = models.CharField(
        "motivo da rejeição", max_length=3, choices=Motivo.choices, blank=True
    )
    observacao = models.TextField("observação", blank=True)
    origem = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refeitas",
        help_text="Movimentação rejeitada que esta refaz.",
    )
    vinculo = models.ForeignKey(
        Vinculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes",
        verbose_name="plano da pessoa",
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    history = HistoricalRecords()
    objects = MovimentacaoQuerySet.as_manager()

    class Meta:
        verbose_name = "movimentação"
        verbose_name_plural = "movimentações"
        ordering = ["vigencia", "beneficiario__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "beneficiario", "contrato"],
                condition=Q(etapa__in=ETAPAS_EM_ABERTO),
                name="movimentacao_uma_em_aberto_por_plano",
                violation_error_message=(
                    "Já existe uma movimentação em aberto desta pessoa neste plano."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} de {self.beneficiario} em {self.contrato.ramo}"

    def get_absolute_url(self) -> str:
        return reverse("movimentacoes:detalhe", args=[self.pk])

    @property
    def eh_inclusao(self) -> bool:
        return self.tipo == self.Tipo.INCLUSAO

    @property
    def em_aberto(self) -> bool:
        return self.etapa in ETAPAS_EM_ABERTO

    @property
    def proximas_etapas(self) -> list[str]:
        return PROXIMAS_ETAPAS[self.etapa]

    @property
    def apos_o_fechamento(self) -> bool:
        """Chegou depois do dia de fechamento do mês (vigência vai para o outro mês)."""
        fechamento = self.contrato.dia_fechamento
        return bool(fechamento and self.recebida_em.day > fechamento)

    @property
    def dias_em_aberto(self) -> int | None:
        return (date.today() - self.recebida_em).days if self.em_aberto else None

    def clean(self) -> None:
        super().clean()
        if not (self.beneficiario_id and self.contrato_id):
            return
        pessoa = self.beneficiario
        if self.contrato.cliente_id != pessoa.cliente_id:
            raise ValidationError({"contrato": "O plano deve ser do mesmo cliente da pessoa."})
        if self.solicitante_id and self.solicitante.cliente_id != pessoa.cliente_id:
            raise ValidationError({"solicitante": "O solicitante deve ser desta empresa."})
        if self._state.adding:
            no_plano = pessoa.vinculos.filter(contrato=self.contrato, data_exclusao__isnull=True)
            if self.eh_inclusao and no_plano.exists():
                raise ValidationError({"contrato": "Esta pessoa já está neste plano."})
            if not self.eh_inclusao and not no_plano.exists():
                raise ValidationError({"contrato": "Esta pessoa não está neste plano."})

    def save(self, *args, **kwargs):
        self.cliente_id = self.beneficiario.cliente_id
        if self.vigencia is None:
            self.vigencia = self.contrato.vigencia_sugerida(self.recebida_em)
        super().save(*args, **kwargs)

    def mudar_etapa(self, nova: str, **dados) -> None:
        """Avança o pedido. Aprovar mexe no plano da pessoa; o resto só registra."""
        if nova not in self.proximas_etapas:
            raise ValidationError(
                f"Não é possível passar de {self.get_etapa_display()} para {Etapa(nova).label}."
            )
        for campo, valor in dados.items():
            setattr(self, campo, valor)
        with transaction.atomic():
            if nova == Etapa.REJEITADA and not self.motivo_rejeicao:
                raise ValidationError("Informe o motivo da rejeição.")
            if nova == Etapa.APROVADA:
                self._aplicar_no_plano()
            if nova == Etapa.CONCLUIDA:
                self._concluir()
            self.etapa = nova
            self.save()

    def _aplicar_no_plano(self) -> None:
        if self.eh_inclusao:
            vinculo = Vinculo(
                beneficiario=self.beneficiario,
                contrato=self.contrato,
                data_inclusao=self.vigencia,
                carteirinha=self.carteirinha,
            )
            try:
                vinculo.full_clean()
            except ValidationError as erro:
                mensagens = erro.messages
                if not self.beneficiario.eh_titular:
                    mensagens.append("Se o titular também está sendo incluído, aprove-o primeiro.")
                raise ValidationError(mensagens) from erro
            vinculo.save()
        else:
            do_plano = self.beneficiario.vinculos.filter(contrato=self.contrato)
            vinculo = do_plano.filter(data_exclusao__isnull=True).first()
            if vinculo:
                vinculo.encerrar(self.vigencia)
            else:
                # Já saiu (ex.: junto com o titular): só liga o pedido ao plano encerrado.
                vinculo = do_plano.order_by("-data_exclusao").first()
                if vinculo is None:
                    raise ValidationError("Esta pessoa não está neste plano.")
        self.vinculo = vinculo

    def _concluir(self) -> None:
        if not self.eh_inclusao:
            return
        if not self.carteirinha:
            raise ValidationError("Informe o número da carteirinha para concluir.")
        if not self.carteirinha_enviada_em:
            self.carteirinha_enviada_em = date.today()
        if self.vinculo_id and self.vinculo.carteirinha != self.carteirinha:
            self.vinculo.carteirinha = self.carteirinha
            self.vinculo.save(update_fields=["carteirinha", "atualizado_em"])

    def refazer(self, usuario) -> "Movimentacao":
        """Nova movimentação a partir de uma rejeitada (ex.: rasura, prazo da entrevista)."""
        if self.etapa != Etapa.REJEITADA:
            raise ValidationError("Só é possível refazer uma movimentação rejeitada.")
        hoje = date.today()
        nova = Movimentacao(
            tipo=self.tipo,
            cliente=self.cliente,
            beneficiario=self.beneficiario,
            contrato=self.contrato,
            solicitante=self.solicitante,
            recebida_em=hoje,
            enviada_em=hoje,
            vigencia=self.contrato.vigencia_sugerida(hoje),
            origem=self,
            registrada_por=usuario,
            observacao=f"Refaz a movimentação rejeitada ({self.get_motivo_rejeicao_display()}).",
        )
        nova.full_clean()
        nova.save()
        return nova
