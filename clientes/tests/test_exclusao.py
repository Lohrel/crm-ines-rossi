from datetime import date

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apolices.models import Contrato, Ramo, Seguradora
from clientes.models import Cliente, Contato, Unidade

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client, db):
    from contas.models import Usuario

    usuario = Usuario.objects.create_superuser("chefe", password="senha-forte-de-teste")
    client.force_login(usuario)
    return client


def contrato_para(cliente, unidades=()):
    contrato = Contrato.objects.create(
        cliente=cliente,
        seguradora=Seguradora.objects.create(nome="Seg"),
        ramo=Ramo.objects.get(nome="Saúde"),
        numero="C-1",
        modalidade="EM" if cliente.eh_empresa else "IF",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=5,
    )
    contrato.unidades.set(unidades)
    return contrato


def test_excluir_empresa_digitando_o_nome(admin, empresa, matriz, filial, contato_rh):
    url = reverse("clientes:excluir", args=[empresa.pk])
    assert "Supermercados Exemplo" in admin.get(url).content.decode()
    resposta = admin.post(url, {"confirmacao": "  supermercados   EXEMPLO "})
    assert resposta.status_code == 302
    assert resposta.url == reverse("clientes:lista")
    assert not Cliente.objects.exists()
    assert not Unidade.objects.exists()
    assert not Contato.objects.exists()
    assert Cliente.history.filter(history_type="-").get().history_user.username == "chefe"


def test_texto_errado_nao_exclui(admin, empresa, matriz):
    resposta = admin.post(
        reverse("clientes:excluir", args=[empresa.pk]), {"confirmacao": "Supermercados"}
    )
    assert resposta.status_code == 200
    assert "não confere" in resposta.content.decode()
    assert Cliente.objects.filter(pk=empresa.pk).exists()


def test_confirmacao_vazia_nao_exclui(admin, pessoa):
    admin.post(reverse("clientes:excluir", args=[pessoa.pk]), {"confirmacao": ""})
    assert Cliente.objects.filter(pk=pessoa.pk).exists()


def test_empresa_com_contrato_nao_pode_ser_excluida(admin, empresa, matriz):
    contrato_para(empresa, [matriz])
    url = reverse("clientes:excluir", args=[empresa.pk])
    conteudo = admin.get(url).content.decode()
    assert "Não é possível excluir" in conteudo
    assert "1 contrato ligado(s)" in conteudo
    admin.post(url, {"confirmacao": empresa.nome})
    assert Cliente.objects.filter(pk=empresa.pk).exists()


def test_filial_coberta_por_contrato_nao_pode_ser_excluida(admin, empresa, filial):
    contrato_para(empresa, [filial])
    admin.post(reverse("clientes:excluir_unidade", args=[filial.pk]), {"confirmacao": str(filial)})
    assert Unidade.objects.filter(pk=filial.pk).exists()


def test_empresa_com_filial_em_contrato_nao_pode_ser_excluida(admin, empresa, filial):
    contrato_para(empresa, [filial])
    assert empresa.bloqueios_para_excluir()


def test_excluir_filial_mantem_a_empresa(admin, empresa, matriz, filial, contato_rh):
    resposta = admin.post(
        reverse("clientes:excluir_unidade", args=[filial.pk]), {"confirmacao": "Exemplo Centro"}
    )
    assert resposta.status_code == 302
    assert resposta.url == empresa.get_absolute_url()
    assert list(empresa.unidades.all()) == [matriz]
    assert not Contato.objects.exists()


def test_excluir_pessoa_fisica(admin, pessoa):
    admin.post(reverse("clientes:excluir", args=[pessoa.pk]), {"confirmacao": "João Exemplo"})
    assert not Cliente.objects.exists()


def test_usuario_sem_permissao_nao_ve_botao_nem_exclui(logado, empresa):
    assert "Excluir" not in logado.get(empresa.get_absolute_url()).content.decode()
    resposta = logado.post(
        reverse("clientes:excluir", args=[empresa.pk]), {"confirmacao": empresa.nome}
    )
    assert resposta.status_code == 403
    assert Cliente.objects.filter(pk=empresa.pk).exists()


def test_permissao_pode_ser_dada_a_um_funcionario(logado, usuario, empresa):
    usuario.user_permissions.add(Permission.objects.get(codename="delete_cliente"))
    resposta = logado.post(
        reverse("clientes:excluir", args=[empresa.pk]), {"confirmacao": empresa.nome}
    )
    assert resposta.status_code == 302
    assert not Cliente.objects.exists()


def test_botoes_de_exclusao_ficam_no_fim_da_pagina(admin, empresa, matriz):
    """Excluir fica depois do histórico, longe de Editar e Nova unidade."""
    pagina = admin.get(empresa.get_absolute_url()).content.decode()
    historico = pagina.index("Histórico de alterações")
    for url in (
        reverse("clientes:excluir", args=[empresa.pk]),
        reverse("clientes:excluir_unidade", args=[matriz.pk]),
    ):
        assert pagina.index(url) > historico
