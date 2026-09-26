from datetime import date

import pytest

from apolices.models import Contrato, Ramo, Seguradora


@pytest.fixture
def seguradora(db):
    return Seguradora.objects.create(nome="Seguradora Exemplo")


@pytest.fixture
def saude(db):
    return Ramo.objects.get(nome="Saúde")


@pytest.fixture
def contrato_empresa(empresa, matriz, filial, seguradora, saude):
    contrato = Contrato.objects.create(
        cliente=empresa,
        seguradora=seguradora,
        ramo=saude,
        numero="SAU-001",
        produto="Plano Empresarial",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        data_renovacao=date(2027, 1, 1),
        dia_vencimento=10,
        corretora_envia_boleto=True,
    )
    contrato.unidades.set([filial])
    return contrato
