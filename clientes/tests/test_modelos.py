import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from clientes.models import Cliente, Contato, Unidade

from .conftest import CNPJ_FILIAL, CNPJ_MATRIZ, CPF_1

pytestmark = pytest.mark.django_db


def test_pessoa_fisica_sem_cpf_e_barrada_pelo_banco():
    with pytest.raises(IntegrityError):
        Cliente.objects.create(tipo="PF", nome="Sem CPF")


def test_empresa_com_cpf_e_barrada_pelo_banco():
    with pytest.raises(IntegrityError):
        Cliente.objects.create(tipo="PJ", nome="Empresa", cpf=CPF_1)


def test_cpf_invalido_nao_passa_na_validacao():
    cliente = Cliente(tipo="PF", nome="X", cpf="12345678900")
    with pytest.raises(ValidationError) as erro:
        cliente.full_clean()
    assert "cpf" in erro.value.message_dict


def test_cpf_duplicado_tem_mensagem_clara(pessoa):
    with pytest.raises(ValidationError, match="Já existe um cliente com este CPF"):
        Cliente(tipo="PF", nome="Outro", cpf=pessoa.cpf).full_clean()


def test_varias_empresas_sem_cpf_sao_permitidas():
    Cliente.objects.create(tipo="PJ", nome="A")
    Cliente.objects.create(tipo="PJ", nome="B")
    assert Cliente.objects.empresas().count() == 2


def test_nova_matriz_desmarca_a_anterior(matriz, filial):
    filial.matriz = True
    filial.save()
    matriz.refresh_from_db()
    assert not matriz.matriz
    assert Unidade.objects.filter(cliente=filial.cliente, matriz=True).get() == filial


def test_novo_contato_principal_desmarca_o_anterior(contato_rh, filial):
    novo = Contato.objects.create(unidade=filial, nome="Pedro", principal=True)
    contato_rh.refresh_from_db()
    assert not contato_rh.principal
    assert novo.principal


def test_documento_principal_da_empresa_e_o_cnpj_da_matriz(empresa, filial, matriz):
    assert empresa.documento_principal == "11.222.333/0001-81"


def test_documento_principal_da_pessoa_e_o_cpf(pessoa):
    assert pessoa.documento_principal == "529.982.247-25"


@pytest.mark.parametrize(
    "termo", ["supermercados", "exemplo centro", "11.222.333/0002-62", "0002", "Filial Ltda"]
)
def test_busca_encontra_empresa_por_qualquer_unidade(empresa, matriz, filial, termo):
    assert list(Cliente.objects.buscar(termo)) == [empresa]


def test_busca_por_cpf_com_ou_sem_pontuacao(pessoa):
    assert list(Cliente.objects.buscar("529.982")) == [pessoa]
    assert list(Cliente.objects.buscar("52998224725")) == [pessoa]


def test_busca_vazia_devolve_todos(pessoa, empresa):
    assert Cliente.objects.buscar("  ").count() == 2


def test_cnpj_unico_entre_empresas(matriz):
    outra = Cliente.objects.create(tipo="PJ", nome="Outra")
    with pytest.raises(ValidationError):
        Unidade(cliente=outra, cnpj=CNPJ_MATRIZ, razao_social="X").full_clean()


def test_historico_registra_alteracoes(pessoa):
    pessoa.telefone = "11 99999-0000"
    pessoa.save()
    assert pessoa.history.count() == 2
    assert pessoa.history.first().history_type == "~"


def test_unidade_str_prefere_nome_fantasia(filial, matriz):
    assert str(filial) == "Exemplo Centro"
    assert str(matriz) == "Supermercados Exemplo Ltda"
    assert CNPJ_FILIAL  # usado nos fixtures
