"""Linha do tempo das alterações de um cliente e de tudo que pertence a ele.

Outros apps (ex.: contratos) acrescentam seus registros com `LinhaDoTempo.registrar_fonte`.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import chain

from clientes.models import Cliente, Contato, DocumentoDoCliente, Unidade


@dataclass(frozen=True)
class Evento:
    quando: datetime
    quem: str
    acao: str
    registro: str
    campos: list[str]


FonteDeHistorico = Callable[[Cliente], Iterable]


def _cadastro_do_cliente(cliente: Cliente) -> Iterable:
    return chain(
        Cliente.history.filter(id=cliente.pk),
        Unidade.history.filter(cliente_id=cliente.pk),
        Contato.history.filter(cliente_id=cliente.pk),
        DocumentoDoCliente.history.filter(cliente_id=cliente.pk),
    )


class LinhaDoTempo:
    ACOES = {"+": "Criou", "~": "Alterou", "-": "Removeu"}
    fontes: list[FonteDeHistorico] = [_cadastro_do_cliente]

    def __init__(self, alvo, limite: int = 30) -> None:
        # O alvo é o cliente; subclasses podem usar outro registro (ex.: um beneficiário).
        self.alvo = alvo
        self.limite = limite

    @classmethod
    def registrar_fonte(cls, fonte: FonteDeHistorico) -> None:
        if fonte not in cls.fontes:
            cls.fontes.append(fonte)

    def eventos(self) -> list[Evento]:
        registros = chain.from_iterable(fonte(self.alvo) for fonte in self.fontes)
        recentes = sorted(registros, key=lambda r: r.history_date, reverse=True)[: self.limite]
        return [self._evento(r) for r in recentes]

    def _evento(self, registro) -> Evento:
        modelo = registro.instance_type
        instancia = registro.instance
        # O registro pode ter um nome mais preciso que o do modelo (ex.: veículo ou imóvel).
        nome = getattr(instancia, "nome_no_historico", "") or modelo._meta.verbose_name
        return Evento(
            quando=registro.history_date,
            quem=str(registro.history_user) if registro.history_user else "Sistema",
            acao=self.ACOES.get(registro.history_type, registro.history_type),
            registro=f"{nome.capitalize()}: {instancia}",
            campos=self._campos_alterados(registro, modelo),
        )

    @staticmethod
    def _campos_alterados(registro, modelo) -> list[str]:
        if registro.history_type != "~" or registro.prev_record is None:
            return []
        diferenca = registro.diff_against(registro.prev_record, excluded_fields=["atualizado_em"])
        return [str(modelo._meta.get_field(m.field).verbose_name) for m in diferenca.changes]
