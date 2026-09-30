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
    # Numa linha a partir de 992 px (lg): cabe num notebook com zoom de 125%.
    assert "navbar-expand-lg" in pagina
    assert 'data-bs-target="#menu-principal"' in pagina
    assert 'id="menu-principal"' in pagina
    assert 'aria-label="Menu principal"' in pagina


def test_nome_de_quem_entrou_num_botao_com_o_sair(logado):
    pagina = logado.get(reverse("inicio")).content.decode()
    # No computador, o primeiro nome abre um menu pequeno com o nome inteiro e o Sair.
    assert 'data-bs-toggle="dropdown" aria-expanded="false">Ana</button>' in pagina
    assert '<span class="dropdown-item-text small text-body-secondary">Ana Lima</span>' in pagina
    assert '<button type="submit" class="dropdown-item">Sair</button>' in pagina
    # No menu recolhido (tablet e celular), o nome e o Sair ficam à vista.
    assert '<span class="navbar-text">Ana Lima</span>' in pagina
    assert pagina.count(f'action="{reverse("logout")}"') == 2


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
    for template in ["base.html", "registration/login.html", "500.html"]:
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


@pytest.mark.parametrize(
    ("rota", "resumo"),
    [
        ("movimentacoes:lista", "Como funciona esta lista"),
        ("boletos:lista", "Como funciona esta lista"),
        ("pendencias:lista", "Como funciona esta lista"),
        ("calendario:mes", "Como funciona o calendário"),
    ],
)
def test_explicacoes_recolhidas_num_como_funciona(logado, rota, resumo):
    pagina = logado.get(reverse(rota)).content.decode()
    assert '<details class="como-funciona' in pagina
    assert f"<summary>{resumo}</summary>" in pagina


def test_pagina_nao_encontrada_em_portugues(logado):
    resposta = logado.get("/clientes/999999/")
    assert resposta.status_code == 404
    pagina = resposta.content.decode()
    assert "Página não encontrada" in pagina and "Voltar para o início" in pagina
    assert 'id="menu-principal"' in pagina


def test_sem_permissao_em_portugues(logado, pessoa):
    resposta = logado.get(reverse("clientes:excluir", args=[pessoa.pk]))
    assert resposta.status_code == 403
    assert "Você não tem permissão para esta página" in resposta.content.decode()


def test_erro_do_servidor_em_portugues(rf):
    from django.views.defaults import server_error

    resposta = server_error(rf.get("/"))
    assert resposta.status_code == 500
    pagina = resposta.content.decode()
    assert "Algo deu errado" in pagina and "img/logo-completo-cor.svg" in pagina
