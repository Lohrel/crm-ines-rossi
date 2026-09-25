import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env import Env


def test_str_obrigatoria_ausente_gera_erro_claro():
    with pytest.raises(ImproperlyConfigured, match="FALTANDO"):
        Env({}).str("FALTANDO")


def test_str_usa_padrao():
    assert Env({}).str("X", padrao="y") == "y"


@pytest.mark.parametrize("valor", ["true", "True", "1", "sim", "on"])
def test_bool_verdadeiro(valor):
    assert Env({"X": valor}).bool("X") is True


def test_bool_falso_e_padrao():
    assert Env({"X": "false"}).bool("X", padrao=True) is False
    assert Env({}).bool("X", padrao=True) is True


def test_list_ignora_espacos_e_vazios():
    assert Env({"X": " a, b ,,c "}).list("X") == ["a", "b", "c"]
