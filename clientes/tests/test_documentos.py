import pytest

from clientes.documentos import CNPJ, CPF

# Números gerados apenas para teste (dígitos verificadores válidos, sem titular real).
CPF_VALIDO = "529.982.247-25"
CNPJ_VALIDO = "11.222.333/0001-81"


@pytest.mark.parametrize("valor", [CPF_VALIDO, "52998224725", " 529 982 247 25 "])
def test_cpf_valido_com_ou_sem_pontuacao(valor):
    assert CPF(valor).valido()


@pytest.mark.parametrize("valor", ["529.982.247-24", "111.111.111-11", "123", "", None])
def test_cpf_invalido(valor):
    assert not CPF(valor).valido()


def test_cpf_formatado():
    assert CPF("52998224725").formatado() == CPF_VALIDO


@pytest.mark.parametrize("valor", [CNPJ_VALIDO, "11222333000181"])
def test_cnpj_valido(valor):
    assert CNPJ(valor).valido()


@pytest.mark.parametrize("valor", ["11.222.333/0001-80", "00.000.000/0000-00", "1122233300018"])
def test_cnpj_invalido(valor):
    assert not CNPJ(valor).valido()


def test_cnpj_formatado():
    assert CNPJ("11222333000181").formatado() == CNPJ_VALIDO


def test_formatado_de_valor_incompleto_devolve_so_digitos():
    assert CPF("123.4").formatado() == "1234"
