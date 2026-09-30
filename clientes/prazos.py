def texto_do_prazo(dias: int) -> str:
    """Quanto falta para uma data, ex.: "vence em 3 dias", "vence hoje" ou "venceu há 2 dias"."""
    textos = {-1: "venceu ontem", 0: "vence hoje", 1: "vence amanhã"}
    if dias in textos:
        return textos[dias]
    return f"vence em {dias} dias" if dias > 0 else f"venceu há {-dias} dias"


def quando(dias: int) -> str:
    """Distância até uma data, ex.: "hoje", "amanhã", "em 5 dias" ou "há 3 dias"."""
    textos = {-1: "ontem", 0: "hoje", 1: "amanhã"}
    if dias in textos:
        return textos[dias]
    return f"em {dias} dias" if dias > 0 else f"há {-dias} dias"
