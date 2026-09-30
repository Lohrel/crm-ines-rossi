"""O que as importações de planilha (.xlsx) têm em comum: comparar textos e ler com segurança."""

import re
import unicodedata
import zipfile

NAO_LEU = "Não foi possível ler o arquivo. Salve-o como Excel (.xlsx) e envie de novo."


class PlanilhaInvalidaError(Exception):
    pass


def chave(texto) -> str:
    """Texto para comparar: sem acento, em maiúsculas e com espaços simples."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", texto).upper().split())


def mesmo_codigo(um, outro) -> bool:
    """04521 e 4521 são o mesmo código (matrícula, SUB): o Excel tira o zero da frente."""
    um, outro = chave(um), chave(outro)
    if um.isdigit() and outro.isdigit():
        return um.lstrip("0") == outro.lstrip("0")
    return um == outro


def conferir_tamanho(arquivo, limite: int) -> None:
    """Recusa o arquivo que, descompactado, passa do limite (proteção contra "zip bomb")."""
    try:
        with zipfile.ZipFile(arquivo) as pacote:
            total = sum(item.file_size for item in pacote.infolist())
    except zipfile.BadZipFile as erro:
        raise PlanilhaInvalidaError(NAO_LEU) from erro
    finally:
        arquivo.seek(0)
    if total > limite:
        raise PlanilhaInvalidaError("A planilha é grande demais para importar.")
