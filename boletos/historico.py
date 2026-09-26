from collections.abc import Iterable
from dataclasses import replace

from boletos.models import Boleto
from clientes.historico import Evento, LinhaDoTempo


def _do_boleto(boleto: Boleto) -> Iterable:
    return Boleto.history.filter(id=boleto.pk)


class LinhaDoTempoDoBoleto(LinhaDoTempo):
    """Quem registrou o boleto, quem registrou o envio e o que mudou."""

    fontes = [_do_boleto]

    def _evento(self, registro) -> Evento:
        # Mostra a situação em que o boleto ficou depois de cada alteração.
        evento = super()._evento(registro)
        return replace(evento, registro=f"situação: {registro.instance.situacao.label}")
