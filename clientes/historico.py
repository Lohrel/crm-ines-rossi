"""Linha do tempo das alterações de um cliente e de tudo que pertence a ele.

Outros apps (ex.: contratos) acrescentam seus registros com `LinhaDoTempo.registrar_fonte`.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import chain

from clientes.models import Cliente, Contato, Unidade


@dataclass(frozen=True)
class Evento:
    quando: datetime
    quem: str
    acao: str
    registro: str
    campos: list[str]


FonteDeHistorico = Callable[[Cliente], Iterable]


def _cadastro_do_cliente(cliente: Cliente) -> Iterable:
    unidades_ids = list(cliente.unidades.values_list("pk", flat=True))
    return chain(
        Cliente.history.filter(id=cliente.pk),
        Unidade.history.filter(cliente_id=cliente.pk),
        Contato.history.filter(unidade_id__in=unidades_ids),
    )


class LinhaDoTempo:
    ACOES = {"+": "Criou", "~": "Alterou", "-": "Removeu"}
    fontes: list[FonteDeHistorico] = [_cadastro_do_cliente]

    def __init__(self, cliente: Cliente, limite: int = 30) -> None:
        self.cliente = cliente
        self.limite = limite

    @classmethod
    def registrar_fonte(cls, fonte: FonteDeHistorico) -> None:
        if fonte not in cls.fontes:
            cls.fontes.append(fonte)

    def eventos(self) -> list[Evento]:
        registros = chain.from_iterable(fonte(self.cliente) for fonte in self.fontes)
        recentes = sorted(registros, key=lambda r: r.history_date, reverse=True)[: self.limite]
        return [self._evento(r) for r in recentes]

    def _evento(self, registro) -> Evento:
        modelo = registro.instance_type
        return Evento(
            quando=registro.history_date,
            quem=str(registro.history_user) if registro.history_user else "Sistema",
            acao=self.ACOES.get(registro.history_type, registro.history_type),
            registro=f"{modelo._meta.verbose_name.capitalize()}: {registro.instance}",
            campos=self._campos_alterados(registro, modelo),
        )

    @staticmethod
    def _campos_alterados(registro, modelo) -> list[str]:
        if registro.history_type != "~" or registro.prev_record is None:
            return []
        diferenca = registro.diff_against(registro.prev_record, excluded_fields=["atualizado_em"])
        return [str(modelo._meta.get_field(m.field).verbose_name) for m in diferenca.changes]
