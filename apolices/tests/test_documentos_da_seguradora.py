"""Página da seguradora com os documentos dela (regras de produto, tabelas...)."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apolices.models import DocumentoDaSeguradora, Ramo

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def pasta_de_anexos(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def pdf(nome="regras.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4 teste", content_type="application/pdf")


def test_lista_leva_a_pagina_da_seguradora(logado, seguradora):
    lista = logado.get(reverse("apolices:seguradoras")).content.decode()
    assert seguradora.get_absolute_url() in lista
    pagina = logado.get(seguradora.get_absolute_url())
    assert pagina.status_code == 200
    assert "Nenhum documento anexado" in pagina.content.decode()


def test_editar_volta_para_a_pagina_da_seguradora(logado, seguradora):
    resposta = logado.post(
        reverse("apolices:editar_seguradora", args=[seguradora.pk]),
        {"nome": "Seguradora Nova", "cor": "", "ativo": "on"},
    )
    assert resposta.url == seguradora.get_absolute_url()


def test_anexar_e_baixar_regras_do_produto(logado, seguradora, pasta_de_anexos):
    dental = Ramo.objects.get(nome="Dental")
    resposta = logado.post(
        reverse("apolices:novo_documento", args=[seguradora.pk]),
        {"tipo": "REG", "ramo": dental.pk, "descricao": "Regras de inclusão", "arquivo": pdf()},
    )
    assert resposta.url == f"{seguradora.get_absolute_url()}#documentos"
    documento = DocumentoDaSeguradora.objects.get()
    assert documento.enviado_por.username == "ana"
    assert documento.arquivo.name.startswith(f"seguradoras/{seguradora.pk}/")
    assert (Path(pasta_de_anexos) / documento.arquivo.name).exists()

    pagina = logado.get(seguradora.get_absolute_url()).content.decode()
    assert "Regras de inclusão" in pagina
    assert "Dental" in pagina
    assert "criou Documento da seguradora: Regras de inclusão" in pagina
    lista = logado.get(reverse("apolices:seguradoras")).content.decode()
    assert f'{seguradora.get_absolute_url()}#documentos">1</a>' in lista

    download = logado.get(reverse("apolices:baixar_documento", args=[documento.pk]))
    assert b"".join(download.streaming_content) == b"%PDF-1.4 teste"
    assert "no-store" in download["Cache-Control"]


def test_documento_da_seguradora_exige_login(client, seguradora):
    documento = DocumentoDaSeguradora.objects.create(
        seguradora=seguradora, tipo="TAB", arquivo=pdf(), nome_original="tabela.pdf"
    )
    resposta = client.get(reverse("apolices:baixar_documento", args=[documento.pk]))
    assert "/entrar/" in resposta.url


def tabela(seguradora):
    return DocumentoDaSeguradora.objects.create(
        seguradora=seguradora, tipo="TAB", arquivo=pdf(), nome_original="tabela.pdf"
    )


def test_so_administrador_exclui_documento_da_seguradora(logado, seguradora):
    url = reverse("apolices:excluir_documento", args=[tabela(seguradora).pk])
    assert "Excluir registros" not in logado.get(seguradora.get_absolute_url()).content.decode()
    assert logado.post(url, {"confirmacao": "tabela.pdf"}).status_code == 403
    assert DocumentoDaSeguradora.objects.exists()


def test_excluir_documento_da_seguradora(
    admin, seguradora, pasta_de_anexos, django_capture_on_commit_callbacks
):
    documento = tabela(seguradora)
    caminho = Path(pasta_de_anexos) / documento.arquivo.name
    url = reverse("apolices:excluir_documento", args=[documento.pk])
    assert (
        "Excluir documento tabela.pdf" in admin.get(seguradora.get_absolute_url()).content.decode()
    )

    with django_capture_on_commit_callbacks(execute=True):
        admin.post(url, {"confirmacao": "tabela.pdf"})
    assert not DocumentoDaSeguradora.objects.exists()
    assert not caminho.exists()
