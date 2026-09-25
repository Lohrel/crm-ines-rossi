import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher

from contas.models import Usuario

pytestmark = pytest.mark.django_db


def test_modelo_de_usuario_e_o_do_crm():
    assert get_user_model() is Usuario


def test_nome_exibicao_usa_nome_completo_ou_login():
    assert str(Usuario(username="joao", first_name="João", last_name="Souza")) == "João Souza"
    assert str(Usuario(username="joao")) == "joao"


def test_senha_armazenada_com_argon2():
    usuario = Usuario.objects.create_user(username="ana", password="senha-forte-de-teste")
    assert identify_hasher(usuario.password).algorithm == "argon2"
