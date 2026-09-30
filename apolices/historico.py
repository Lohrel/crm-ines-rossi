from collections.abc import Iterable
from itertools import chain

from apolices.models import Contrato, Subfatura
from clientes.models import Cliente


def historico_de_contratos(cliente: Cliente) -> Iterable:
    return chain(
        Contrato.history.filter(cliente_id=cliente.pk),
        Subfatura.history.filter(contrato__cliente_id=cliente.pk),
    )
