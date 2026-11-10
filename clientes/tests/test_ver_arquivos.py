"""PDF e imagens anexados abertos dentro do sistema, sem baixar (etapa 20)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apolices.models import DocumentoDaSeguradora
from beneficiarios.models import Anexo
from clientes.models import DocumentoDoCliente

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4 teste"
PNG = b"\x89PNG\r\n\x1a\n teste"


@pytest.fixture(autouse=True)
def pasta_de_anexos(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def arquivo(nome, conteudo=PDF):
    return SimpleUploadedFile(nome, conteudo)


@pytest.fixture
def documento_do_cliente(empresa):
    def criar(nome="contrato.pdf", conteudo=PDF):
        return DocumentoDoCliente.objects.create(
            cliente=empresa, tipo="CON", arquivo=arquivo(nome, conteudo), nome_original=nome
        )

    return criar


@pytest.fixture
def documento_da_seguradora(seguradora):
    def criar(nome="tabela.pdf", conteudo=PDF):
        return DocumentoDaSeguradora.objects.create(
            seguradora=seguradora, tipo="TAB", arquivo=arquivo(nome, conteudo), nome_original=nome
        )

    return criar


@pytest.fixture
def anexo_da_pessoa(titular):
    def criar(nome="dps.pdf", conteudo=PDF):
        return Anexo.objects.create(
            beneficiario=titular, tipo="DPS", arquivo=arquivo(nome, conteudo), nome_original=nome
        )

    return criar


# Os três tipos de anexo, com as rotas de cada um.
TIPOS = [
    ("documento_do_cliente", "clientes:ver_documento", "clientes:abrir_documento"),
    ("documento_da_seguradora", "apolices:ver_documento", "apolices:abrir_documento"),
    ("anexo_da_pessoa", "beneficiarios:ver_anexo", "beneficiarios:abrir_anexo"),
]


@pytest.mark.parametrize(("fabrica", "rota_ver", "rota_abrir"), TIPOS)
def test_pdf_aparece_numa_pagina_do_sistema(request, logado, fabrica, rota_ver, rota_abrir):
    anexado = request.getfixturevalue(fabrica)("Contrato assinado.pdf")
    pagina = logado.get(reverse(rota_ver, args=[anexado.pk]))
    assert pagina.status_code == 200
    html = pagina.content.decode()
    url_abrir = reverse(rota_abrir, args=[anexado.pk])
    assert f'<object data="{url_abrir}" type="application/pdf"' in html
    assert ">Baixar</a>" in html
    assert "Contrato assinado.pdf" in html

    aberto = logado.get(url_abrir)
    assert aberto.status_code == 200
    assert b"".join(aberto.streaming_content) == PDF
    assert aberto["Content-Type"] == "application/pdf"
    assert aberto["Content-Disposition"].startswith("inline")
    assert aberto["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in aberto["Content-Security-Policy"]
    assert aberto["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in aberto["Cache-Control"]


@pytest.mark.parametrize(("fabrica", "rota_ver", "rota_abrir"), TIPOS)
def test_imagem_aparece_sem_poder_rodar_nada(request, logado, fabrica, rota_ver, rota_abrir):
    anexado = request.getfixturevalue(fabrica)("RG frente.PNG", PNG)
    html = logado.get(reverse(rota_ver, args=[anexado.pk])).content.decode()
    assert f'<img src="{reverse(rota_abrir, args=[anexado.pk])}"' in html

    aberto = logado.get(reverse(rota_abrir, args=[anexado.pk]))
    assert aberto["Content-Type"] == "image/png"
    assert aberto["Content-Disposition"].startswith("inline")
    assert "sandbox" in aberto["Content-Security-Policy"]
    assert "script-src" not in aberto["Content-Security-Policy"]


def test_tipo_entregue_vem_da_extensao_e_nao_do_conteudo(logado, documento_do_cliente):
    # Uma página da web disfarçada de imagem chega como imagem (e o navegador não a abre).
    disfarcado = documento_do_cliente("foto.jpg", b"<html><script>alert(1)</script></html>")
    aberto = logado.get(reverse("clientes:abrir_documento", args=[disfarcado.pk]))
    assert aberto["Content-Type"] == "image/jpeg"
    assert aberto["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(("fabrica", "rota_ver", "rota_abrir"), TIPOS)
def test_word_continua_so_com_download(request, logado, fabrica, rota_ver, rota_abrir):
    anexado = request.getfixturevalue(fabrica)("ficha.docx", b"PK teste")
    pagina = logado.get(reverse(rota_ver, args=[anexado.pk]))
    assert pagina.status_code == 302
    assert "/baixar/" in pagina.url
    aberto = logado.get(reverse(rota_abrir, args=[anexado.pk]))
    assert aberto["Content-Disposition"].startswith("attachment")


@pytest.mark.parametrize(("fabrica", "rota_ver", "rota_abrir"), TIPOS)
def test_ver_exige_login(request, client, fabrica, rota_ver, rota_abrir):
    anexado = request.getfixturevalue(fabrica)()
    for rota in (rota_ver, rota_abrir):
        resposta = client.get(reverse(rota, args=[anexado.pk]))
        assert resposta.status_code == 302
        assert "/entrar/" in resposta.url


def test_arquivo_que_sumiu_do_disco_mostra_aviso(logado, documento_do_cliente):
    documento = documento_do_cliente()
    documento.arquivo.storage.delete(documento.arquivo.name)
    resposta = logado.get(reverse("clientes:ver_documento", args=[documento.pk]), follow=True)
    assert "não foi encontrado no servidor" in resposta.content.decode()


def test_listas_abrem_pdf_no_sistema_e_baixam_word(
    logado,
    empresa,
    seguradora,
    titular,
    documento_do_cliente,
    documento_da_seguradora,
    anexo_da_pessoa,
):
    pdf, word = documento_do_cliente(), documento_do_cliente("ficha.docx", b"PK")
    html = logado.get(empresa.get_absolute_url()).content.decode()
    assert reverse("clientes:ver_documento", args=[pdf.pk]) in html
    assert reverse("clientes:baixar_documento", args=[pdf.pk]) in html
    assert reverse("clientes:ver_documento", args=[word.pk]) not in html
    assert reverse("clientes:baixar_documento", args=[word.pk]) in html

    tabela = documento_da_seguradora()
    html = logado.get(seguradora.get_absolute_url()).content.decode()
    assert reverse("apolices:ver_documento", args=[tabela.pk]) in html

    dps = anexo_da_pessoa()
    html = logado.get(titular.get_absolute_url()).content.decode()
    assert reverse("beneficiarios:ver_anexo", args=[dps.pk]) in html
    assert reverse("beneficiarios:baixar_anexo", args=[dps.pk]) in html
