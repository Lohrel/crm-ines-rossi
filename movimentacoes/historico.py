from collections.abc import Iterable
from dataclasses import replace

from beneficiarios.models import Beneficiario
from clientes.historico import Evento, LinhaDoTempo
from movimentacoes.models import Movimentacao


def _do_pedido(movimentacao: Movimentacao) -> Iterable:
    return Movimentacao.history.filter(id=movimentacao.pk)


def movimentacoes_da_pessoa(beneficiario: Beneficiario) -> Iterable:
    return Movimentacao.history.filter(beneficiario_id=beneficiario.pk)


class LinhaDoTempoDaMovimentacao(LinhaDoTempo):
    """Quem registrou o pedido e quem mudou cada etapa, e quando."""

    fontes = [_do_pedido]

    def _evento(self, registro) -> Evento:
        # Mostra a etapa em que o pedido ficou depois de cada alteração.
        evento = super()._evento(registro)
        return replace(evento, registro=f"etapa: {registro.instance.get_etapa_display()}")
