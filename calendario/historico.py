from collections.abc import Iterable

from calendario.models import Evento
from clientes.historico import LinhaDoTempo


def _do_evento(evento: Evento) -> Iterable:
    return Evento.history.filter(id=evento.pk)


class LinhaDoTempoDoEvento(LinhaDoTempo):
    """Quem anotou o evento e quem mudou o quê. O evento não é de um cliente."""

    fontes = [_do_evento]
