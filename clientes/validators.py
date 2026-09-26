from django.core.exceptions import ValidationError

from clientes.documentos import CNPJ, CPF, Documento


def _validar(documento: Documento) -> None:
    if not documento.valido():
        raise ValidationError(f"{documento.nome} inválido.", code="invalido")


def validar_cpf(valor: str) -> None:
    _validar(CPF(valor))


def validar_cnpj(valor: str) -> None:
    _validar(CNPJ(valor))
