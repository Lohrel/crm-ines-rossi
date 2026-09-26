"""CPF e CNPJ: limpeza, validação dos dígitos verificadores e formatação."""

import re
from abc import ABC, abstractmethod


class Documento(ABC):
    """Documento brasileiro com dígitos verificadores (CPF ou CNPJ).

    Guarda apenas os dígitos; a pontuação é só para exibição.
    """

    tamanho: int
    nome: str

    def __init__(self, valor: str) -> None:
        self.digitos = re.sub(r"\D", "", valor or "")

    def valido(self) -> bool:
        if len(self.digitos) != self.tamanho or len(set(self.digitos)) == 1:
            return False
        base = self.digitos[:-2]
        return self.digitos == base + self._calcular_verificadores(base)

    def formatado(self) -> str:
        if len(self.digitos) != self.tamanho:
            return self.digitos
        return self._formatar()

    def __str__(self) -> str:
        return self.formatado()

    @abstractmethod
    def _pesos(self, tamanho_base: int) -> list[int]: ...

    @abstractmethod
    def _formatar(self) -> str: ...

    def _calcular_verificadores(self, base: str) -> str:
        for _ in range(2):
            pesos = self._pesos(len(base))
            soma = sum(int(d) * p for d, p in zip(base, pesos, strict=True))
            resto = soma % 11
            base += "0" if resto < 2 else str(11 - resto)
        return base[-2:]


class CPF(Documento):
    tamanho = 11
    nome = "CPF"

    def _pesos(self, tamanho_base: int) -> list[int]:
        return list(range(tamanho_base + 1, 1, -1))

    def _formatar(self) -> str:
        d = self.digitos
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


class CNPJ(Documento):
    tamanho = 14
    nome = "CNPJ"

    def _pesos(self, tamanho_base: int) -> list[int]:
        pesos = [2, 3, 4, 5, 6, 7, 8, 9] * 2
        return list(reversed(pesos[:tamanho_base]))

    def _formatar(self) -> str:
        d = self.digitos
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
