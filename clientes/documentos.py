"""CPF e CNPJ: limpeza, validação dos dígitos verificadores e formatação."""

import re
from abc import ABC, abstractmethod


class Documento(ABC):
    """Documento brasileiro com dígitos verificadores (CPF ou CNPJ).

    Guarda só os caracteres significativos (sem pontuação, em maiúsculas);
    a pontuação é só para exibição.
    """

    tamanho: int
    nome: str
    # Caracteres aceitos no documento; o resto (pontos, barras, traços) é descartado.
    caracteres_aceitos = r"0-9"
    # Formato completo aceito, sem pontuação.
    formato: re.Pattern

    def __init__(self, valor: str) -> None:
        texto = (valor or "").upper()
        self.valor = re.sub(rf"[^{self.caracteres_aceitos}]", "", texto)

    def valido(self) -> bool:
        if not self.formato.fullmatch(self.valor) or len(set(self.valor)) == 1:
            return False
        base = self.valor[:-2]
        return self.valor == base + self._calcular_verificadores(base)

    def formatado(self) -> str:
        if len(self.valor) != self.tamanho:
            return self.valor
        return self._formatar()

    def __str__(self) -> str:
        return self.formatado()

    @abstractmethod
    def _pesos(self, tamanho_base: int) -> list[int]: ...

    @abstractmethod
    def _formatar(self) -> str: ...

    @staticmethod
    def _numero(caractere: str) -> int:
        """Valor usado na conta: dígitos valem eles mesmos, letras valem ASCII - 48 (A=17)."""
        return ord(caractere) - ord("0")

    def _calcular_verificadores(self, base: str) -> str:
        for _ in range(2):
            pesos = self._pesos(len(base))
            soma = sum(self._numero(c) * p for c, p in zip(base, pesos, strict=True))
            resto = soma % 11
            base += "0" if resto < 2 else str(11 - resto)
        return base[-2:]


class CPF(Documento):
    tamanho = 11
    nome = "CPF"
    formato = re.compile(r"\d{11}")

    def _pesos(self, tamanho_base: int) -> list[int]:
        return list(range(tamanho_base + 1, 1, -1))

    def _formatar(self) -> str:
        d = self.valor
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


class CNPJ(Documento):
    """CNPJ numérico ou alfanumérico (emitido pela Receita desde julho de 2026).

    No alfanumérico, as 12 primeiras posições podem ter letras e os dois
    dígitos verificadores continuam numéricos.
    """

    tamanho = 14
    nome = "CNPJ"
    caracteres_aceitos = r"0-9A-Z"
    formato = re.compile(r"[0-9A-Z]{12}\d{2}")

    def _pesos(self, tamanho_base: int) -> list[int]:
        pesos = [2, 3, 4, 5, 6, 7, 8, 9] * 2
        return list(reversed(pesos[:tamanho_base]))

    def _formatar(self) -> str:
        d = self.valor
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
