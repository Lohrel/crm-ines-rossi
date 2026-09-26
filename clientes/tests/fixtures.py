import pytest

from clientes.models import Cliente, Contato, Unidade
from contas.models import Usuario

# Documentos fictícios, gerados só para teste (dígitos verificadores válidos).
CPF_1 = "52998224725"
CPF_2 = "11144477735"
CNPJ_MATRIZ = "11222333000181"
CNPJ_FILIAL = "11222333000262"


@pytest.fixture
def usuario(db):
    return Usuario.objects.create_user(
        username="ana", password="senha-forte-de-teste", first_name="Ana", last_name="Lima"
    )


@pytest.fixture
def logado(client, usuario):
    client.force_login(usuario)
    return client


@pytest.fixture
def pessoa(db):
    return Cliente.objects.create(tipo="PF", nome="João Exemplo", cpf=CPF_1)


@pytest.fixture
def empresa(db):
    return Cliente.objects.create(tipo="PJ", nome="Supermercados Exemplo")


@pytest.fixture
def matriz(empresa):
    return Unidade.objects.create(
        cliente=empresa, cnpj=CNPJ_MATRIZ, razao_social="Supermercados Exemplo Ltda", matriz=True
    )


@pytest.fixture
def filial(empresa):
    return Unidade.objects.create(
        cliente=empresa,
        cnpj=CNPJ_FILIAL,
        razao_social="Supermercados Exemplo Filial Ltda",
        nome_fantasia="Exemplo Centro",
    )


@pytest.fixture
def contato_rh(filial):
    return Contato.objects.create(unidade=filial, nome="Carla RH", cargo="RH", principal=True)
