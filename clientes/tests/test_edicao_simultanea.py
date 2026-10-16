"""Duas pessoas editando o mesmo registro ao mesmo tempo, e anexos que sumiram do disco."""

import os
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apolices.models import DocumentoDaSeguradora
from beneficiarios.models import Anexo
from clientes.models import DocumentoDoCliente
from clientes.views import CAMPO_DA_VERSAO
from contas.models import Usuario
from movimentacoes.models import Etapa, Movimentacao

pytestmark = pytest.mark.django_db


@pytest.fixture
def bia(db):
    return Usuario.objects.create_user(
        username="bia", password="senha-forte-de-teste", first_name="Bia", last_name="Souza"
    )


def entrar(usuario) -> Client:
    cliente = Client()
    cliente.force_login(usuario)
    return cliente


def dados_da_tela(resposta) -> dict:
    """O que o navegador enviaria ao salvar sem mudar nada."""
    form = resposta.context["form"]
    dados = {}
    for campo in form:
        valor = campo.value()
        if valor is not None:
            dados[campo.html_name] = valor
    return dados


def test_quem_salva_depois_nao_apaga_sem_saber_o_que_outra_pessoa_gravou(usuario, bia, pessoa):
    ana, outra = entrar(usuario), entrar(bia)
    url = reverse("clientes:editar", args=[pessoa.pk])
    tela_da_ana, tela_da_bia = dados_da_tela(ana.get(url)), dados_da_tela(outra.get(url))

    tela_da_ana["telefone"] = "(11) 1111-1111"
    assert ana.post(url, tela_da_ana).status_code == 302
    tela_da_bia["email"] = "novo@exemplo.com"
    resposta = outra.post(url, tela_da_bia)

    assert resposta.status_code == 200
    pagina = resposta.content.decode()
    assert "Ana Lima gravou este registro às" in pagina
    pessoa.refresh_from_db()
    assert pessoa.telefone == "(11) 1111-1111"
    assert pessoa.email == ""
    # A tela continua com o que a Bia digitou; se ela salvar de novo, vale a tela dela.
    assert 'value="novo@exemplo.com"' in pagina
    assert outra.post(url, dados_da_tela(resposta)).status_code == 302
    pessoa.refresh_from_db()
    assert pessoa.email == "novo@exemplo.com"


def test_edicao_sem_ninguem_no_meio_grava_normalmente(logado, pessoa):
    url = reverse("clientes:editar", args=[pessoa.pk])
    dados = dados_da_tela(logado.get(url))
    assert dados[CAMPO_DA_VERSAO]
    dados["telefone"] = "(11) 2222-2222"

    assert logado.post(url, dados).status_code == 302
    pessoa.refresh_from_db()
    assert pessoa.telefone == "(11) 2222-2222"


def test_tela_aberta_antes_da_atualizacao_ainda_grava(logado, pessoa):
    url = reverse("clientes:editar", args=[pessoa.pk])
    dados = dados_da_tela(logado.get(url))
    del dados[CAMPO_DA_VERSAO]
    dados["telefone"] = "(11) 3333-3333"

    assert logado.post(url, dados).status_code == 302


def test_cadastro_novo_nao_tem_o_campo_da_versao(logado):
    resposta = logado.get(reverse("clientes:novo_pf"))
    assert CAMPO_DA_VERSAO not in resposta.context["form"].fields


def test_mesmo_pedido_aprovado_por_duas_pessoas(usuario, bia, titular, saude):
    from movimentacoes.tests.test_movimentacoes import pedido

    mov = pedido(titular, saude)
    ana, outra = entrar(usuario), entrar(bia)
    url = reverse("movimentacoes:mudar_etapa", args=[mov.pk, "APR"])
    tela_da_ana, tela_da_bia = dados_da_tela(ana.get(url)), dados_da_tela(outra.get(url))

    assert ana.post(url, tela_da_ana).status_code == 302
    resposta = outra.post(url, tela_da_bia)

    # Já aprovado: a Bia não tem mais o que aprovar, e a pessoa entrou no plano uma vez só.
    assert resposta.status_code == 404
    assert titular.vinculos.count() == 1


def test_pedido_que_mudou_no_meio_nao_muda_de_novo(titular, saude):
    from movimentacoes.tests.test_movimentacoes import pedido

    mov = pedido(titular, saude)
    lida_antes = Movimentacao.objects.get(pk=mov.pk)
    mov.mudar_etapa(Etapa.APROVADA, vigencia=date(2026, 10, 1))

    with pytest.raises(ValidationError, match="Outra pessoa mudou a etapa"):
        lida_antes.mudar_etapa(Etapa.APROVADA, vigencia=date(2026, 10, 1))
    assert titular.vinculos.count() == 1


# ------------------------------------------------------------------
# Arquivo que sumiu do disco (o registro ficou, o arquivo não)
# ------------------------------------------------------------------


@pytest.fixture
def pasta_de_anexos(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def pdf():
    return SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 teste")


def test_documento_do_cliente_que_sumiu(logado, empresa, pasta_de_anexos, caplog):
    documento = DocumentoDoCliente.objects.create(
        cliente=empresa, tipo="CON", arquivo=pdf(), nome_original="contrato.pdf"
    )
    os.remove(documento.arquivo.path)

    resposta = logado.get(reverse("clientes:baixar_documento", args=[documento.pk]), follow=True)

    assert resposta.redirect_chain[0][0] == documento.get_absolute_url()
    assert "não foi encontrado no servidor" in resposta.content.decode()
    assert documento.arquivo.name in caplog.text


def test_documento_da_seguradora_que_sumiu(logado, seguradora, pasta_de_anexos):
    documento = DocumentoDaSeguradora.objects.create(
        seguradora=seguradora, tipo="REG", arquivo=pdf(), nome_original="regras.pdf"
    )
    os.remove(documento.arquivo.path)

    resposta = logado.get(reverse("apolices:baixar_documento", args=[documento.pk]))

    assert resposta.status_code == 302


def test_anexo_do_beneficiario_que_sumiu(logado, titular, pasta_de_anexos):
    anexo = Anexo.objects.create(
        beneficiario=titular, tipo="DPS", arquivo=pdf(), nome_original="dps.pdf"
    )
    os.remove(anexo.arquivo.path)

    resposta = logado.get(reverse("beneficiarios:baixar_anexo", args=[anexo.pk]), follow=True)

    assert resposta.redirect_chain[0][0] == titular.get_absolute_url()
    assert "“dps.pdf” não foi encontrado" in resposta.content.decode()
