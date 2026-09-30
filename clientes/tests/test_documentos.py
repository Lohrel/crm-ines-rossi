import pytest
from django.core.exceptions import ValidationError

from clientes.documentos import CNPJ, CPF, cpf_ou_cnpj
from clientes.forms import CpfOuCnpjField

# Números gerados apenas para teste (dígitos verificadores válidos, sem titular real).
CPF_VALIDO = "529.982.247-25"
CNPJ_VALIDO = "11.222.333/0001-81"
# Exemplo publicado pela Receita Federal para o CNPJ alfanumérico.
CNPJ_ALFANUMERICO = "12.ABC.345/01DE-35"


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


@pytest.mark.parametrize("valor", [CNPJ_ALFANUMERICO, "12ABC34501DE35", "12.abc.345/01de-35"])
def test_cnpj_alfanumerico_valido(valor):
    assert CNPJ(valor).valido()


def test_cnpj_alfanumerico_guardado_em_maiusculas_e_formatado():
    cnpj = CNPJ("12abc34501de35")
    assert cnpj.valor == "12ABC34501DE35"
    assert cnpj.formatado() == CNPJ_ALFANUMERICO


@pytest.mark.parametrize(
    "valor",
    [
        "12.ABC.345/01DE-36",  # verificador errado
        "12.ABC.345/01DE-3A",  # verificador com letra
        "12.ÁBC.345/01DE-35",  # acento não é aceito
    ],
)
def test_cnpj_alfanumerico_invalido(valor):
    assert not CNPJ(valor).valido()


def test_cpf_nao_aceita_letras():
    assert CPF("529.982.247-2A").valor == "5299822472"
    assert not CPF("529.982.247-2A").valido()


@pytest.mark.parametrize(
    ("valor", "tipo"),
    [(CPF_VALIDO, CPF), (CNPJ_VALIDO, CNPJ), ("12.abc.345/01de-35", CNPJ)],
)
def test_cpf_ou_cnpj_pelo_tamanho(valor, tipo):
    documento = cpf_ou_cnpj(valor)
    assert isinstance(documento, tipo) and documento.valido()


@pytest.mark.parametrize("valor", ["", None, "123", "529.982.247-2A"])
def test_nem_cpf_nem_cnpj(valor):
    assert cpf_ou_cnpj(valor) is None


def test_campo_de_cpf_ou_cnpj():
    campo = CpfOuCnpjField(required=False)
    assert campo.clean(" 529.982.247-25 ") == "52998224725"
    assert campo.clean(CNPJ_ALFANUMERICO.lower()) == "12ABC34501DE35"
    assert campo.clean("") == ""
    for invalido in ["529.982.247-24", "12.ABC.345/01DE-36", "123"]:
        with pytest.raises(ValidationError, match="CPF ou CNPJ inválido"):
            campo.clean(invalido)
    assert campo.prepare_value("12ABC34501DE35") == CNPJ_ALFANUMERICO
    assert campo.prepare_value("52998224725") == CPF_VALIDO
