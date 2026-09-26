"""Leitura das configurações vindas de variáveis de ambiente (arquivo .env)."""

import os

from django.core.exceptions import ImproperlyConfigured


class Env:
    """Acesso tipado às variáveis de ambiente, com erro claro quando falta alguma."""

    _VERDADEIROS = {"1", "true", "yes", "sim", "on"}

    def __init__(self, fonte: dict[str, str] | None = None) -> None:
        self._fonte = os.environ if fonte is None else fonte

    def str(self, nome: str, padrao: str | None = None) -> str:
        valor = self._fonte.get(nome, padrao)
        if valor is None or valor == "":
            raise ImproperlyConfigured(f"Variável de ambiente obrigatória ausente: {nome}")
        return valor

    def bool(self, nome: str, padrao: bool = False) -> bool:
        valor = self._fonte.get(nome)
        if valor is None:
            return padrao
        return valor.strip().lower() in self._VERDADEIROS

    def list(self, nome: str, padrao: str = "") -> list[str]:
        valor = self._fonte.get(nome, padrao)
        return [item.strip() for item in valor.split(",") if item.strip()]
