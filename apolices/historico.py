from collections.abc import Iterable
from itertools import chain

from apolices.models import (
    BemSegurado,
    Contrato,
    DocumentoDaSeguradora,
    Plano,
    Seguradora,
    Subfatura,
)
from clientes.historico import LinhaDoTempo
from clientes.models import Cliente


def historico_de_contratos(cliente: Cliente) -> Iterable:
    return chain(
        Contrato.history.filter(cliente_id=cliente.pk),
        Subfatura.history.filter(contrato__cliente_id=cliente.pk),
        Plano.history.filter(contrato__cliente_id=cliente.pk),
        BemSegurado.history.filter(contrato__cliente_id=cliente.pk),
    )


def _do_bem(bem: BemSegurado) -> Iterable:
    return BemSegurado.history.filter(id=bem.pk)


class LinhaDoTempoDoBem(LinhaDoTempo):
    """Quem cadastrou o veículo ou o imóvel e quem mudou o quê."""

    fontes = [_do_bem]


def _da_seguradora(seguradora: Seguradora) -> Iterable:
    return chain(
        Seguradora.history.filter(id=seguradora.pk),
        DocumentoDaSeguradora.history.filter(seguradora_id=seguradora.pk),
    )


class LinhaDoTempoDaSeguradora(LinhaDoTempo):
    """Alterações do cadastro da seguradora e dos documentos dela."""

    fontes = [_da_seguradora]
