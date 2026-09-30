"""Veículos e imóveis das apólices de auto e imóvel (etapa 9). Todos os dados são fictícios."""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apolices.models import BemSegurado, Contrato, Ramo
from clientes.models import Cliente

pytestmark = pytest.mark.django_db


@pytest.fixture
def auto(db):
    return Ramo.objects.get(nome="Auto")


@pytest.fixture
def imovel(db):
    return Ramo.objects.get(nome="Imóvel")


def contrato(cliente, seguradora, ramo, numero):
    return Contrato.objects.create(
        cliente=cliente,
        seguradora=seguradora,
        ramo=ramo,
        numero=numero,
        modalidade="IF",
        inicio_vigencia=date(2026, 3, 1),
        data_renovacao=date(2027, 3, 1),
        dia_vencimento=5,
    )


@pytest.fixture
def contrato_auto(pessoa, seguradora, auto):
    return contrato(pessoa, seguradora, auto, "AUTO-1")


@pytest.fixture
def contrato_imovel(pessoa, seguradora, imovel):
    return contrato(pessoa, seguradora, imovel, "RES-1")


def veiculo_em(contrato_auto, placa, descricao="Hatch Compacto 1.0", **extra):
    return BemSegurado.objects.create(
        contrato=contrato_auto, tipo="VEI", descricao=descricao, placa=placa, **extra
    )


@pytest.fixture
def veiculo(contrato_auto):
    return veiculo_em(
        contrato_auto,
        "ABC1D23",
        ano_modelo="2024/2025",
        renavam="00123456789",
        danos_materiais=Decimal("100000"),
        premio=Decimal("2500"),
    )


def dados_veiculo(**extra):
    return {
        "descricao": "Hatch Compacto 1.0",
        "placa": "abc-1d23",
        "ano_modelo": "2024/2025",
        "cor": "Prata",
        "combustivel": "Flex",
        "renavam": "0012345678-9",
        "proprietario": "",
        "documento_proprietario": "",
        "condutor_principal": "João Exemplo",
        "cep": "01001-000",
        "danos_materiais": "100000",
        "danos_corporais": "",
        "danos_morais": "",
        "premio": "2500.00",
        "observacao": "",
        **extra,
    }


def dados_imovel(**extra):
    return {
        "descricao": "Casa",
        "cep": "01310-100",
        "logradouro": "Rua Exemplo",
        "numero": "10",
        "complemento": "",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "uf": "SP",
        "proprietario": "Maria Exemplo",
        "documento_proprietario": "111.444.777-35",
        "capitais": "Incêndio R$ 100 mil\nVendaval R$ 10 mil",
        "premio": "480.00",
        "observacao": "",
        **extra,
    }


def test_ramos_de_auto_e_imovel_guardam_veiculos_e_imoveis():
    bens = dict(Ramo.objects.values_list("nome", "bem_segurado"))
    assert bens["Auto"] == "VEI" and bens["Imóvel"] == "IMO"
    assert bens["Saúde"] == bens["Dental"] == bens["Vida"] == ""


@pytest.mark.parametrize(
    ("digitada", "guardada", "formatada"),
    [("abc1d23", "ABC1D23", "ABC1D23"), ("xyz9876", "XYZ9876", "XYZ-9876")],
)
def test_placa_em_maiusculas_e_antiga_com_traco(contrato_auto, digitada, guardada, formatada):
    carro = BemSegurado(contrato=contrato_auto, tipo="VEI", descricao="Hatch", placa=digitada)
    carro.full_clean()
    assert carro.placa == guardada and carro.placa_formatada == formatada


@pytest.mark.parametrize("placa", ["AB12345", "ABCD123", "1BC1D23", "ABC1DD3"])
def test_placa_invalida(contrato_auto, placa):
    carro = BemSegurado(contrato=contrato_auto, tipo="VEI", descricao="Hatch", placa=placa)
    with pytest.raises(ValidationError, match="Placa inválida"):
        carro.full_clean()


def test_nome_do_veiculo_e_do_imovel(contrato_auto, contrato_imovel):
    carro = BemSegurado(contrato=contrato_auto, tipo="VEI", descricao="Hatch", placa="XYZ9876")
    assert str(carro) == "Hatch · XYZ-9876" and carro.nome_para_confirmar == "XYZ-9876"
    sem_placa = BemSegurado(contrato=contrato_auto, tipo="VEI", descricao="Hatch")
    assert str(sem_placa) == "Hatch" and sem_placa.nome_para_confirmar == "Hatch"
    casa = BemSegurado(
        contrato=contrato_imovel,
        tipo="IMO",
        descricao="Casa",
        logradouro="Rua Exemplo",
        numero="10",
    )
    assert str(casa) == "Casa · Rua Exemplo, 10" and casa.nome_para_confirmar == "Casa"


def test_cadastrar_veiculo_pela_apolice(logado, pessoa, contrato_auto):
    url = reverse("apolices:novo_bem", args=[contrato_auto.pk])
    pagina = logado.get(url).content.decode()
    assert "Novo veículo de João Exemplo" in pagina
    assert 'name="placa"' in pagina and 'name="capitais"' not in pagina

    # O CPF/CNPJ aceita o CNPJ com letras; o Renavam, colado com o traço.
    resposta = logado.post(url, dados_veiculo(documento_proprietario="12.abc.345/01de-35"))
    assert resposta.status_code == 302
    assert resposta.url == f"{pessoa.get_absolute_url()}#bens"
    carro = BemSegurado.objects.get()
    assert carro.contrato == contrato_auto and carro.tipo == "VEI"
    assert carro.placa == "ABC1D23" and carro.renavam == "00123456789"
    assert carro.documento_proprietario == "12ABC34501DE35"
    assert carro.danos_materiais == Decimal("100000") and carro.danos_corporais is None
    pagina = logado.get(resposta.url).content.decode()
    assert "Veículo cadastrado." in pagina


def test_cadastro_do_veiculo_confere_placa_renavam_e_documento(logado, contrato_auto):
    resposta = logado.post(
        reverse("apolices:novo_bem", args=[contrato_auto.pk]),
        dados_veiculo(placa="AB-12345", renavam="123", documento_proprietario="529.982.247-24"),
    )
    assert resposta.status_code == 200
    pagina = resposta.content.decode()
    assert "Placa inválida. Use ABC1D23 ou ABC-1234." in pagina
    assert "O Renavam tem 9 ou 11 números." in pagina
    assert "CPF ou CNPJ inválido." in pagina
    assert not BemSegurado.objects.exists()


def test_cadastrar_imovel_pela_apolice(logado, pessoa, contrato_imovel):
    url = reverse("apolices:novo_bem", args=[contrato_imovel.pk])
    pagina = logado.get(url).content.decode()
    assert "Novo imóvel de João Exemplo" in pagina
    assert 'name="capitais"' in pagina and 'name="placa"' not in pagina

    resposta = logado.post(url, dados_imovel())
    assert resposta.status_code == 302
    casa = BemSegurado.objects.get()
    assert casa.tipo == "IMO" and casa.placa == "" and casa.uf == "SP"
    assert casa.documento_proprietario == "11144477735"
    pagina = logado.get(casa.get_absolute_url()).content.decode()
    assert "111.444.777-35" in pagina and "Maria Exemplo" in pagina
    assert "Incêndio R$ 100 mil\nVendaval R$ 10 mil" in pagina


def test_contrato_de_ramo_sem_veiculo_nem_imovel(logado, pessoa, seguradora, saude):
    plano = contrato(pessoa, seguradora, saude, "SAU-1")
    assert logado.get(reverse("apolices:novo_bem", args=[plano.pk])).status_code == 404


def test_ramo_novo_marcado_para_veiculos(logado, pessoa, seguradora):
    frota = Ramo.objects.create(nome="Frota", bem_segurado="VEI")
    apolice = contrato(pessoa, seguradora, frota, "FR-1")
    pagina = logado.get(reverse("apolices:novo_bem", args=[apolice.pk])).content.decode()
    assert "Novo veículo" in pagina and 'name="placa"' in pagina


def test_pagina_do_cliente_mostra_veiculos_e_imoveis(logado, pessoa, veiculo, contrato_imovel):
    pagina = logado.get(pessoa.get_absolute_url()).content.decode()
    assert "Veículos e imóveis segurados" in pagina
    assert f'<a href="{veiculo.get_absolute_url()}" class="fw-semibold">Hatch Compacto 1.0</a>' in (
        pagina
    )
    assert '<span class="placa">ABC1D23</span>' in pagina
    assert reverse("apolices:novo_bem", args=[veiculo.contrato.pk]) in pagina
    assert "Adicionar veículo" in pagina and "Adicionar imóvel" in pagina
    assert "Nenhum imóvel cadastrado nesta apólice." in pagina
    assert "criou Veículo: Hatch Compacto 1.0 · ABC1D23" in pagina


def test_cliente_sem_auto_nem_imovel_nao_mostra_o_cartao(logado, contrato_empresa, empresa):
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Veículos e imóveis segurados" not in pagina


def test_tabela_de_contratos_mostra_as_placas(logado, contrato_auto):
    placas = ["ABC1D23", "BCD2E34", "CDE3F45", "DEF4G56"]
    carros = [
        veiculo_em(contrato_auto, placa, descricao=f"Carro {n}") for n, placa in enumerate(placas)
    ]
    pagina = logado.get(reverse("apolices:contratos")).content.decode()
    for carro in carros[:3]:
        assert f'href="{carro.get_absolute_url()}" class="placa"' in pagina
    assert "DEF4G56" not in pagina and "e mais 1" in pagina


def test_busca_pela_placa(logado, pessoa, veiculo, contrato_empresa, empresa):
    veiculo_em(veiculo.contrato, "XYZ1D23", descricao="Moto 160")
    # Com ou sem traço, em minúsculas ou só um pedaço; o cliente aparece uma vez só.
    assert list(Cliente.objects.buscar("abc-1d23")) == [pessoa]
    assert list(Cliente.objects.buscar("1D23")) == [pessoa]
    lista = logado.get(reverse("clientes:lista"), {"q": "abc1d23"}).content.decode()
    assert "João Exemplo" in lista and "Supermercados Exemplo" not in lista

    url = reverse("apolices:contratos")
    pagina = logado.get(url, {"q": "1d23"}).content.decode()
    assert pagina.count('<div class="small text-body-secondary">AUTO-1</div>') == 1
    assert "SAU-001" not in pagina
    assert "AUTO-1" not in logado.get(url, {"q": "QQQ9Z99"}).content.decode()


def test_veiculos_carregados_numa_consulta_so(logado, pessoa, seguradora, auto, saude, veiculo):
    outro = contrato(pessoa, seguradora, auto, "AUTO-2")
    veiculo_em(outro, "XYZ9876")
    contrato(pessoa, seguradora, saude, "SAU-1")
    urls = [pessoa.get_absolute_url(), reverse("apolices:contratos")]

    def consultas() -> list[tuple[int, int]]:
        """Quantas consultas cada tela faz, e quantas delas buscam veículos e imóveis."""
        contagem = []
        for url in urls:
            with CaptureQueriesContext(connection) as feitas:
                assert logado.get(url).status_code == 200
            sqls = [consulta["sql"] for consulta in feitas.captured_queries]
            contagem.append((len(sqls), sum('"apolices_bemsegurado"' in sql for sql in sqls)))
        return contagem

    antes = consultas()
    assert [aos_bens for _, aos_bens in antes] == [1, 1]
    for n, placa in enumerate(["BCD2E34", "CDE3F45", "DEF4G56"]):
        veiculo_em(veiculo.contrato, placa, descricao=f"Carro {n}")
        veiculo_em(outro, placa.replace("E", "F"), descricao=f"Moto {n}")
    assert consultas() == antes


def test_pagina_do_veiculo(logado, veiculo):
    pagina = logado.get(veiculo.get_absolute_url()).content.decode()
    assert "<h1" in pagina and "Hatch Compacto 1.0" in pagina
    assert "Seguradora Exemplo" in pagina and "apólice AUTO-1" in pagina
    assert "00123456789" in pagina and "R$ 100.000,00" in pagina
    assert "Não contratado" in pagina  # danos corporais e morais em branco
    assert "João Exemplo" in pagina and "(o próprio cliente)" in pagina
    assert "criou o veículo" in pagina
    assert "Excluir registros" not in pagina


def test_editar_veiculo(logado, veiculo):
    url = reverse("apolices:editar_bem", args=[veiculo.pk])
    assert 'value="ABC1D23"' in logado.get(url).content.decode()
    # Só a placa e a cor mudam; o resto fica como estava.
    mudancas = {"placa": "xyz-9876", "cor": "Azul", "combustivel": "", "cep": ""}
    resposta = logado.post(url, dados_veiculo(condutor_principal="", **mudancas))
    assert resposta.status_code == 302 and resposta.url == veiculo.get_absolute_url()
    veiculo.refresh_from_db()
    assert veiculo.placa == "XYZ9876" and veiculo.cor == "Azul"
    pagina = logado.get(veiculo.get_absolute_url()).content.decode()
    assert "Veículo atualizado." in pagina
    alterados = re.search(r"Ana Lima</strong> alterou o veículo\s*<span[^>]*>\((.*?)\)", pagina)
    assert set(alterados.group(1).split(", ")) == {"placa", "cor"}


def test_funcionario_nao_exclui_veiculo(logado, veiculo):
    url = reverse("apolices:excluir_bem", args=[veiculo.pk])
    assert logado.get(url).status_code == 403
    assert logado.post(url, {"confirmacao": "ABC1D23"}).status_code == 403
    assert BemSegurado.objects.exists()


def test_administrador_exclui_veiculo_digitando_a_placa(admin, pessoa, veiculo):
    assert "Excluir registros" in admin.get(veiculo.get_absolute_url()).content.decode()
    url = reverse("apolices:excluir_bem", args=[veiculo.pk])
    assert '<strong class="user-select-all">ABC1D23</strong>' in admin.get(url).content.decode()
    assert admin.post(url, {"confirmacao": "Hatch Compacto 1.0"}).status_code == 200
    assert BemSegurado.objects.exists()

    resposta = admin.post(url, {"confirmacao": " abc1d23 "})
    assert resposta.status_code == 302 and resposta.url == f"{pessoa.get_absolute_url()}#bens"
    assert not BemSegurado.objects.exists()
    assert BemSegurado.history.get(history_type="-").history_user.username == "chefe"
    pagina = admin.get(pessoa.get_absolute_url()).content.decode()
    assert "removeu Veículo: Hatch Compacto 1.0 · ABC1D23" in pagina


def test_paginas_de_veiculos_exigem_login(client, veiculo):
    urls = [
        veiculo.get_absolute_url(),
        reverse("apolices:editar_bem", args=[veiculo.pk]),
        reverse("apolices:novo_bem", args=[veiculo.contrato.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 302
