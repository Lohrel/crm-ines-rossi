"""Fixtures de contratos e beneficiários, compartilhados com as movimentações."""

from datetime import date, timedelta

import pytest

from apolices.models import Contrato, Ramo, Seguradora
from beneficiarios.models import Beneficiario, Vinculo
from clientes.tests.fixtures import CPF_1

HOJE = date.today()
ONTEM = HOJE - timedelta(days=1)


@pytest.fixture
def seguradora():
    return Seguradora.objects.create(nome="Seguradora Exemplo")


def contrato(empresa, seguradora, ramo, numero, unidades):
    novo = Contrato.objects.create(
        cliente=empresa,
        seguradora=seguradora,
        ramo=Ramo.objects.get(nome=ramo),
        numero=numero,
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=10,
    )
    novo.unidades.set(unidades)
    return novo


@pytest.fixture
def saude(empresa, seguradora, matriz, filial):
    return contrato(empresa, seguradora, "Saúde", "S-1", [matriz, filial])


@pytest.fixture
def dental(empresa, seguradora, matriz, filial):
    return contrato(empresa, seguradora, "Dental", "D-1", [matriz, filial])


@pytest.fixture
def titular(empresa, filial):
    return Beneficiario.objects.create(
        cliente=empresa, unidade=filial, nome="Ana Titular", cpf=CPF_1
    )


@pytest.fixture
def conjuge(titular):
    return Beneficiario.objects.create(
        cliente=titular.cliente, titular=titular, parentesco="CJ", nome="Bruno Cônjuge"
    )


@pytest.fixture
def filho(titular):
    return Beneficiario.objects.create(
        cliente=titular.cliente, titular=titular, parentesco="FI", nome="Caio Filho"
    )


def incluir(pessoa, plano, inclusao=ONTEM, exclusao=None):
    vinculo = Vinculo(
        beneficiario=pessoa, contrato=plano, data_inclusao=inclusao, data_exclusao=exclusao
    )
    vinculo.full_clean()
    vinculo.save()
    return vinculo


@pytest.fixture
def admin(client):
    from contas.models import Usuario

    client.force_login(Usuario.objects.create_superuser("chefe", password="senha-forte-de-teste"))
    return client
