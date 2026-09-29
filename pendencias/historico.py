from collections.abc import Iterable
from dataclasses import replace

from clientes.historico import Evento, LinhaDoTempo
from clientes.models import Cliente
from pendencias.models import Pendencia


def pendencias_do_cliente(cliente: Cliente) -> Iterable:
    return Pendencia.history.filter(cliente_id=cliente.pk)


def _da_pendencia(pendencia: Pendencia) -> Iterable:
    return Pendencia.history.filter(id=pendencia.pk)


class LinhaDoTempoDaPendencia(LinhaDoTempo):
    """Quem registrou a pendência, quem concluiu (ou reabriu) e o que mudou."""

    fontes = [_da_pendencia]

    def _evento(self, registro) -> Evento:
        # Mostra a situação em que a pendência ficou depois de cada alteração.
        evento = super()._evento(registro)
        situacao = "concluída" if registro.concluida_em else "em aberto"
        return replace(evento, registro=f"situação: {situacao}")
