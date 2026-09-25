import pytest
from django.urls import reverse

from contas.models import Usuario

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario():
    return Usuario.objects.create_user(
        username="maria", password="senha-forte-de-teste", first_name="Maria", last_name="Silva"
    )


def test_pagina_inicial_exige_login(client):
    resposta = client.get(reverse("inicio"))
    assert resposta.status_code == 302
    assert resposta.url.startswith(reverse("login"))


def test_admin_exige_login(client):
    resposta = client.get("/admin/")
    assert resposta.status_code == 302


def test_login_com_senha_correta_leva_ao_inicio(client, usuario):
    resposta = client.post(
        reverse("login"), {"username": "maria", "password": "senha-forte-de-teste"}
    )
    assert resposta.status_code == 302
    assert resposta.url == reverse("inicio")


def test_login_com_senha_errada_mostra_erro(client, usuario):
    resposta = client.post(reverse("login"), {"username": "maria", "password": "errada"})
    assert resposta.status_code == 200
    assert "Usuário ou senha incorretos" in resposta.content.decode()


def test_inicio_mostra_nome_do_usuario(client, usuario):
    client.force_login(usuario)
    resposta = client.get(reverse("inicio"))
    assert resposta.status_code == 200
    assert "Maria Silva" in resposta.content.decode()


def test_sair_encerra_a_sessao(client, usuario):
    client.force_login(usuario)
    client.post(reverse("logout"))
    assert client.get(reverse("inicio")).status_code == 302


def test_saude_nao_exige_login(client):
    resposta = client.get(reverse("saude"))
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
