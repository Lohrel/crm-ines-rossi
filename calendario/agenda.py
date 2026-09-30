"""Datas do calendário: as anotações da equipe e as que o sistema já conhece.

Entram as anotações (férias, reuniões, aniversários...), os prazos das pendências
em aberto, as renovações dos contratos vigentes e os prazos do mês: o fechamento
das movimentações (uma linha por dia de fechamento) e o envio da planilha do
seguro de vida. As movimentações em si não entram, para não encher o calendário.
"""

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time, timedelta
from itertools import chain

from django.db.models import Count
from django.urls import reverse

from apolices.models import Contrato
from beneficiarios.seguro_de_vida import DIA_LIMITE_DE_ENVIO
from boletos.models import meses_entre
from calendario.models import Evento
from pendencias.models import Pendencia

# Ordem dentro de um dia: quem está fora primeiro, depois os eventos, os prazos do mês, as
# renovações e as pendências.
ORDEM = {"ferias": 0, "evento": 1, "prazo": 2, "renovacao": 3, "pendencia": 4}


@dataclass(frozen=True)
class Item:
    """Uma data do calendário. A categoria dá a cor (veja `.item-calendario` no crm.css)."""

    categoria: str
    titulo: str
    url: str
    rotulo: str
    detalhe: str = ""
    hora: time | None = None
    # Cor da seguradora, nas renovações.
    cor: str = ""
    # Pendência com o prazo já vencido.
    atrasada: bool = False
    # Primeiro dia, nos eventos de vários dias (ex.: férias).
    inicio_do_periodo: date | None = None


def dia_no_mes(dia: int, mes: date) -> date:
    """O dia no mês; em meses mais curtos, o último dia."""
    return mes.replace(day=min(dia, monthrange(mes.year, mes.month)[1]))


def _contratos(quantos: int) -> str:
    return f"{quantos} contrato{'s' if quantos != 1 else ''}"


def lista_por_dia(datas: dict[date, list[Item]], de: date, ate: date) -> list[tuple]:
    """Os dias entre `de` e `ate` que têm alguma data, em ordem, para as listas.

    Um evento de vários dias (ex.: férias) aparece só no primeiro dia da lista, com o
    período no detalhe, para a lista não repetir o mesmo evento dia após dia.
    """
    lista = []
    for dia, itens in sorted(datas.items()):
        if not de <= dia <= ate:
            continue
        do_dia = [
            item
            for item in itens
            if item.inicio_do_periodo is None or dia == max(item.inicio_do_periodo, de)
        ]
        if do_dia:
            lista.append((dia, do_dia))
    return lista


class Agenda:
    """Todas as datas entre `de` e `ate`, com poucas consultas qualquer que seja o período."""

    def __init__(self, de: date, ate: date, hoje: date | None = None):
        self.de = de
        self.ate = ate
        self.hoje = hoje or date.today()

    def por_dia(self) -> dict[date, list[Item]]:
        fontes = chain(self._anotacoes(), self._pendencias(), self._renovacoes(), self._prazos())
        return self._agrupar(fontes)

    def anotacoes_por_dia(self) -> dict[date, list[Item]]:
        """Só o que a equipe anotou (férias, reuniões...), como no quadro da semana do painel."""
        return self._agrupar(self._anotacoes())

    def _agrupar(self, fontes) -> dict[date, list[Item]]:
        dias = defaultdict(list)
        for dia, item in fontes:
            if self.de <= dia <= self.ate:
                dias[dia].append(item)
        for itens in dias.values():
            itens.sort(key=lambda item: (ORDEM[item.categoria], item.hora or time.min, item.titulo))
        return dict(dias)

    def _anotacoes(self):
        for evento in Evento.objects.entre(self.de, self.ate).select_related("funcionario"):
            for inicio, fim in evento.ocorrencias(self.de, self.ate):
                detalhes = [f"de {inicio:%d/%m} a {fim:%d/%m}"] if fim > inicio else []
                if evento.funcionario:
                    detalhes.append(str(evento.funcionario))
                if evento.repete_todo_ano:
                    detalhes.append("todo ano")
                item = Item(
                    categoria="ferias" if evento.tipo == Evento.Tipo.FERIAS else "evento",
                    titulo=evento.titulo,
                    url=evento.get_absolute_url(),
                    rotulo=evento.get_tipo_display(),
                    detalhe=" · ".join(detalhes),
                    hora=evento.hora,
                    inicio_do_periodo=inicio if fim > inicio else None,
                )
                dia = max(inicio, self.de)
                while dia <= min(fim, self.ate):
                    yield dia, item
                    dia += timedelta(days=1)

    def _pendencias(self):
        pendencias = (
            Pendencia.objects.em_aberto()
            .filter(prazo__range=(self.de, self.ate))
            .select_related("cliente", "responsavel")
        )
        for pendencia in pendencias:
            yield (
                pendencia.prazo,
                Item(
                    categoria="pendencia",
                    titulo=pendencia.descricao,
                    url=pendencia.get_absolute_url(),
                    rotulo="Pendência",
                    detalhe=f"{pendencia.cliente} · {pendencia.responsavel}",
                    atrasada=pendencia.prazo < self.hoje,
                ),
            )

    def _renovacoes(self):
        contratos = (
            Contrato.objects.vigentes()
            .filter(data_renovacao__range=(self.de, self.ate))
            .select_related("cliente", "ramo", "seguradora")
        )
        for contrato in contratos:
            yield (
                contrato.data_renovacao,
                Item(
                    categoria="renovacao",
                    titulo=f"Renovação: {contrato.cliente}",
                    url=contrato.cliente.get_absolute_url(),
                    rotulo="Renovação",
                    detalhe=f"{contrato.ramo} · {contrato.seguradora} {contrato.numero}",
                    cor=contrato.seguradora.cor,
                ),
            )

    def _prazos(self):
        vigentes = Contrato.objects.vigentes()
        fechamentos = list(
            vigentes.filter(dia_fechamento__isnull=False)
            .order_by()
            .values_list("dia_fechamento")
            .annotate(contratos=Count("pk"))
        )
        contratos_de_vida = vigentes.com_capital().count()
        for mes in meses_entre(self.de, self.ate):
            for dia, contratos in fechamentos:
                fecham = "fecha" if contratos == 1 else "fecham"
                yield (
                    dia_no_mes(dia, mes),
                    Item(
                        categoria="prazo",
                        titulo="Fechamento das movimentações",
                        url=reverse("movimentacoes:lista"),
                        rotulo="Prazo do mês",
                        detalhe=f"{_contratos(contratos)} {fecham} neste dia",
                    ),
                )
            if contratos_de_vida:
                yield (
                    dia_no_mes(DIA_LIMITE_DE_ENVIO, mes),
                    Item(
                        categoria="prazo",
                        titulo="Envio da planilha do seguro de vida",
                        url=reverse("movimentacoes:planilha"),
                        rotulo="Prazo do mês",
                        detalhe=f"último dia para enviar · {_contratos(contratos_de_vida)}",
                    ),
                )
