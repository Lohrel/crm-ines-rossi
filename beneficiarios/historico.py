from collections.abc import Iterable
from itertools import chain

from beneficiarios.models import Anexo, Beneficiario, Vinculo
from clientes.historico import LinhaDoTempo


def _da_pessoa(beneficiario: Beneficiario) -> Iterable:
    return chain(
        Beneficiario.history.filter(id=beneficiario.pk),
        Vinculo.history.filter(beneficiario_id=beneficiario.pk),
        Anexo.history.filter(beneficiario_id=beneficiario.pk),
    )


class LinhaDoTempoDoBeneficiario(LinhaDoTempo):
    """Alterações da pessoa, dos planos dela e dos anexos."""

    fontes = [_da_pessoa]
