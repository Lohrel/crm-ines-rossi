"""Calendário do escritório: as datas que a equipe anotava no quadro branco.

Férias de funcionário, reuniões, aniversários e outros lembretes. A página do
calendário mostra junto as datas que o sistema já conhece (prazos das
pendências, renovações dos contratos e prazos do mês), montadas em
`calendario/agenda.py`.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from clientes.models import ExclusaoProtegida, Registro


def mesmo_dia_no_ano(data: date, ano: int) -> date:
    """O mesmo dia e mês em outro ano; o 29 de fevereiro vira 28 nos anos que não o têm."""
    try:
        return data.replace(year=ano)
    except ValueError:
        return data.replace(year=ano, day=28)


class EventoQuerySet(models.QuerySet):
    def entre(self, de: date, ate: date):
        """Os que podem acontecer entre as datas: os que se repetem e os que cruzam o período."""
        cruza = Q(fim__gte=de) | Q(fim__isnull=True, inicio__gte=de)
        return self.filter(inicio__lte=ate).filter(Q(repete_todo_ano=True) | cruza)


class Evento(ExclusaoProtegida, Registro):
    class Tipo(models.TextChoices):
        REUNIAO = "REU", "Reunião"
        FERIAS = "FER", "Férias ou ausência"
        ANIVERSARIO = "ANI", "Aniversário"
        OUTRO = "OUT", "Outro"

    titulo = models.CharField(
        "título", max_length=120, help_text="Ex.: Férias da Ana, Reunião com a operadora."
    )
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.REUNIAO)
    inicio = models.DateField("data")
    fim = models.DateField(
        "até",
        null=True,
        blank=True,
        help_text="Só para períodos, como férias: o último dia. Em branco, vale um dia só.",
    )
    hora = models.TimeField(null=True, blank=True, help_text="Ex.: 14:30. Em branco, o dia todo.")
    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="eventos",
        verbose_name="funcionário",
        help_text="Nas férias ou ausências, quem vai estar fora.",
    )
    repete_todo_ano = models.BooleanField(
        "repete todo ano",
        default=False,
        help_text="Ex.: aniversários. Aparece todo ano no mesmo dia.",
    )
    observacao = models.TextField("observação", blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="registrado por",
    )

    history = HistoricalRecords()
    objects = EventoQuerySet.as_manager()

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        ordering = ["inicio", "hora", "titulo"]
        constraints = [
            models.CheckConstraint(
                condition=Q(fim__isnull=True) | Q(fim__gte=models.F("inicio")),
                name="evento_fim_depois_do_inicio",
                violation_error_message="O último dia não pode ser antes da data.",
            ),
        ]

    def __str__(self) -> str:
        return self.titulo

    def get_absolute_url(self) -> str:
        return reverse("calendario:evento", args=[self.pk])

    @property
    def ultimo_dia(self) -> date:
        return self.fim or self.inicio

    def clean(self) -> None:
        super().clean()
        # Um período de um dia só é um dia só.
        if self.fim and self.inicio and self.fim == self.inicio:
            self.fim = None

    def ocorrencias(self, de: date, ate: date) -> list[tuple[date, date]]:
        """Primeiro e último dia de cada vez que o evento acontece entre `de` e `ate`.

        O que se repete todo ano aparece a partir do ano em que foi anotado, no mesmo
        dia e mês; um período repetido tem sempre a mesma duração.
        """
        duracao = self.ultimo_dia - self.inicio
        if self.repete_todo_ano:
            # Começa um ano antes, para pegar um período que atravessa a virada do ano.
            anos = range(max(de.year - 1, self.inicio.year), ate.year + 1)
            inicios = [mesmo_dia_no_ano(self.inicio, ano) for ano in anos]
        else:
            inicios = [self.inicio]
        return [(ini, ini + duracao) for ini in inicios if ini <= ate and ini + duracao >= de]

    def dias_entre(self, de: date, ate: date) -> list[date]:
        """Dias entre `de` e `ate` (inclusive) em que o evento acontece."""
        dias = []
        for inicio, fim in self.ocorrencias(de, ate):
            dia = max(inicio, de)
            while dia <= min(fim, ate):
                dias.append(dia)
                dia += timedelta(days=1)
        return dias
