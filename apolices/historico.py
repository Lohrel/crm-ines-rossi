from collections.abc import Iterable

from apolices.models import Contrato
from clientes.models import Cliente


def historico_de_contratos(cliente: Cliente) -> Iterable:
    return Contrato.history.filter(cliente_id=cliente.pk)
