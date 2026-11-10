"""Busca rápida do menu (etapa 16): pessoas, clientes, contratos e veículos numa busca só."""

from datetime import date

import pytest
from django.urls import reverse

from apolices.models import BemSegurado, TipoDeBem
from beneficiarios.tests.fixtures import ONTEM, incluir
from clientes.models import Cliente
from clientes.tests.fixtures import CPF_2

pytestmark = pytest.mark.django_db


def buscar(cliente_http, termo: str):
    return cliente_http.get(reverse("buscar"), {"q": termo})


def grupos(resposta) -> dict[str, list]:
    return {grupo.titulo: grupo.itens for grupo in resposta.context["resultado"].grupos}


def test_campo_de_busca_aparece_no_menu(logado):
    pagina = logado.get(reverse("inicio")).content.decode()
    assert 'action="/buscar/"' in pagina
    assert 'id="busca-rapida"' in pagina
    assert "js/busca-rapida.js" in pagina


def test_busca_exige_login(client):
    resposta = buscar(client, "Ana")
    assert resposta.status_code == 302
    assert reverse("login") in resposta["Location"]


def test_acha_um_funcionario_sem_saber_a_empresa_e_abre_direto(logado, titular):
    resposta = buscar(logado, "ana titular")
    assert resposta.status_code == 302
    assert resposta["Location"] == titular.get_absolute_url()


def test_palavras_em_qualquer_ordem_e_com_outras_no_meio(logado, empresa, filial):
    pessoa = empresa.beneficiarios.create(unidade=filial, nome="Maria da Silva Exemplo")
    resposta = buscar(logado, "  silva   maria ")
    assert resposta["Location"] == pessoa.get_absolute_url()


def test_acha_pelo_cpf_com_ou_sem_pontos(logado, titular):
    assert buscar(logado, "529.982.247-25")["Location"] == titular.get_absolute_url()
    assert buscar(logado, "52998224725")["Location"] == titular.get_absolute_url()


def test_acha_pela_matricula_e_pela_carteirinha(logado, titular, saude):
    titular.matricula = "M-4321"
    titular.save()
    vinculo = incluir(titular, saude)
    vinculo.carteirinha = "0099887766"
    vinculo.save()
    assert buscar(logado, "m-4321")["Location"] == titular.get_absolute_url()
    assert buscar(logado, "0099887766")["Location"] == titular.get_absolute_url()


def test_varios_resultados_mostram_a_lista_agrupada(logado, titular, conjuge, filho, saude):
    incluir(titular, saude)
    Cliente.objects.create(tipo="PF", nome="Ana Cliente", cpf=CPF_2)
    resposta = buscar(logado, "ana")
    assert resposta.status_code == 200
    achados = grupos(resposta)
    assert [p.nome for p in achados["Pessoas (beneficiários)"]] == ["Ana Titular"]
    assert [c.nome for c in achados["Clientes"]] == ["Ana Cliente"]
    pagina = resposta.content.decode()
    assert "Supermercados Exemplo" in pagina  # o cliente de cada pessoa
    assert "Saúde" in pagina  # os planos em que ela está


def test_busca_curta_demais_nao_procura(logado, titular):
    resposta = buscar(logado, "a")
    assert resposta.status_code == 200
    assert resposta.context["resultado"].grupos == []
    assert "pelo menos 2" in resposta.content.decode()


def test_dependente_mostra_de_quem_e(logado, titular, conjuge, filho):
    # "Caio Filho" e o cliente "Supermercados": mais de um resultado, então mostra a lista.
    pagina = buscar(logado, "ca").content.decode()
    assert "Caio Filho" in pagina
    assert "de Ana Titular" in pagina


def test_quem_saiu_de_todos_os_planos_aparece_como_inativo(logado, empresa, filial, saude):
    saiu = empresa.beneficiarios.create(unidade=filial, nome="Paulo Saiu")
    incluir(saiu, saude, inclusao=date(2026, 1, 1), exclusao=ONTEM)
    novo = empresa.beneficiarios.create(unidade=filial, nome="Paulo Novo")
    resposta = buscar(logado, "paulo")
    pessoas = {p.nome: p for p in grupos(resposta)["Pessoas (beneficiários)"]}
    assert pessoas["Paulo Saiu"].tem_plano and not pessoas["Paulo Saiu"].em_algum_plano
    # Quem acabou de ser cadastrado e ainda não tem plano não é inativo.
    assert not pessoas["Paulo Novo"].tem_plano
    assert novo.get_absolute_url() in resposta.content.decode()


def test_acha_cliente_pelo_cnpj_da_filial(logado, empresa, matriz, filial):
    resposta = buscar(logado, "11.222.333/0002-62")
    assert resposta["Location"] == empresa.get_absolute_url()


def test_acha_contrato_pelo_numero_e_abre_os_contratos_do_cliente(logado, empresa, saude):
    saude.numero = "88-12345"
    saude.save()
    resposta = buscar(logado, "12345")
    assert resposta["Location"] == f"{empresa.get_absolute_url()}#contratos"


def test_nome_do_cliente_nao_repete_os_contratos(logado, empresa, saude, dental):
    resposta = buscar(logado, "Supermercados")
    assert resposta["Location"] == empresa.get_absolute_url()


def test_acha_veiculo_pela_placa(logado, pessoa, seguradora):
    from apolices.models import Contrato, Ramo

    ramo = Ramo.objects.get(nome="Auto")
    apolice = Contrato.objects.create(
        cliente=pessoa,
        seguradora=seguradora,
        ramo=ramo,
        numero="A-1",
        modalidade="IF",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=10,
    )
    carro = BemSegurado.objects.create(
        contrato=apolice, tipo=TipoDeBem.VEICULO, descricao="Carro Exemplo", placa="ABC1D23"
    )
    resposta = buscar(logado, "abc-1d23")
    achados = grupos(resposta)
    # A placa acha o veículo e o cliente dono dele.
    assert achados["Veículos"] == [carro]
    assert achados["Clientes"] == [pessoa]
    assert "ABC1D23" in resposta.content.decode() or "ABC-1D23" in resposta.content.decode()


def test_nada_encontrado(logado, titular):
    resposta = buscar(logado, "Zzzz Ninguém")
    assert resposta.status_code == 200
    assert "Nada encontrado" in resposta.content.decode()


def test_termo_fica_no_campo_do_menu_na_pagina_de_resultados(logado, titular, conjuge):
    pagina = buscar(logado, "Exemplo inexistente").content.decode()
    assert 'value="Exemplo inexistente"' in pagina
