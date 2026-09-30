"""Layout comum: menu, logo, tela de entrada e arquivos do tema da corretora."""

import pathlib
import posixpath
import re

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.urls import reverse

pytestmark = pytest.mark.django_db


def itens_abertos(resposta) -> list[str]:
    return [item["texto"] for item in resposta.context["menu_principal"] if item["aberto"]]


def test_menu_marca_o_item_da_pagina_aberta(logado):
    resposta = logado.get(reverse("boletos:lista"))
    assert itens_abertos(resposta) == ["Boletos"]
    pagina = resposta.content.decode()
    assert '<a class="nav-link active" href="/boletos/" aria-current="page">Boletos</a>' in pagina
    assert '<a class="nav-link" href="/clientes/">Clientes</a>' in pagina


def test_beneficiarios_ficam_em_clientes_e_seguradoras_em_contratos(logado, empresa):
    beneficiarios = logado.get(reverse("beneficiarios:lista", args=[empresa.pk]))
    assert itens_abertos(beneficiarios) == ["Clientes"]
    assert itens_abertos(logado.get(reverse("apolices:seguradoras"))) == ["Contratos"]


def test_inicio_nao_marca_nenhum_item(logado):
    assert itens_abertos(logado.get(reverse("inicio"))) == []


def test_menu_recolhe_no_celular(logado):
    pagina = logado.get(reverse("inicio")).content.decode()
    assert "navbar-expand-lg" in pagina
    assert 'data-bs-target="#menu-principal"' in pagina
    assert 'id="menu-principal"' in pagina


def test_paginas_tem_o_logo_e_o_tema_da_corretora(logado):
    pagina = logado.get(reverse("inicio")).content.decode()
    assert "img/logo-branco.svg" in pagina
    assert "css/crm.css" in pagina
    assert "img/favicon.svg" in pagina
    assert "· Inês Rossi</title>" in pagina


def test_tela_de_entrada_mostra_o_logo_sem_o_menu(client):
    pagina = client.get(reverse("login")).content.decode()
    assert 'class="pagina-login"' in pagina
    assert "img/logo-completo-cor.svg" in pagina
    assert 'alt="Inês Rossi Corretora de Seguros"' in pagina
    assert "menu-principal" not in pagina


def test_arquivos_citados_no_layout_existem():
    pasta = pathlib.Path(settings.BASE_DIR) / "templates"
    for template in ["base.html", "registration/login.html"]:
        texto = (pasta / template).read_text()
        caminhos = re.findall(r"{% static '([^']+)' %}", texto)
        for caminho in caminhos:
            assert finders.find(caminho), f"{template}: {caminho}"


def test_fontes_citadas_no_css_existem_com_a_licenca():
    css = pathlib.Path(finders.find("css/crm.css")).read_text()
    enderecos = re.findall(r'url\("([^"]+)"\)', css)
    assert len(enderecos) == 3
    for endereco in enderecos:
        assert finders.find(posixpath.normpath(posixpath.join("css", endereco))), endereco
    # A licença da Montserrat (SIL OFL) acompanha os arquivos da fonte.
    assert finders.find("fonts/montserrat/OFL.txt")
