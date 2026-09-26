"""Linha do tempo das alterações de um cliente, das suas unidades e dos contatos."""

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


class LinhaDoTempo:
    ACOES = {"+": "Criou", "~": "Alterou", "-": "Removeu"}

    def __init__(self, cliente: Cliente, limite: int = 30) -> None:
        self.cliente = cliente
        self.limite = limite

    def eventos(self) -> list[Evento]:
        unidades_ids = list(self.cliente.unidades.values_list("pk", flat=True))
        registros = chain(
            Cliente.history.filter(id=self.cliente.pk),
            Unidade.history.filter(cliente_id=self.cliente.pk),
            Contato.history.filter(unidade_id__in=unidades_ids),
        )
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
