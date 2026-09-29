from calendar import monthrange
from datetime import date

from django.db import migrations


def vencer_no_proprio_mes(apps, schema_editor):
    """Sem o pós-pagamento, a mensalidade vence no próprio mês de referência.

    As mensalidades geradas para um contrato em pós venciam no mês seguinte. Passam para o
    vencimento do próprio mês pela mesma regra de quando o contrato muda o dia de vencimento:
    só as a enviar, que ainda não venceram e estavam no vencimento de costume.
    """
    Boleto = apps.get_model("boletos", "Boleto")
    mensalidades = Boleto.objects.filter(
        tipo="MEN",
        enviado_em__isnull=True,
        cancelado=False,
        fora_do_vencimento=False,
        vencimento__gte=date.today(),
    ).select_related("contrato")
    for boleto in mensalidades:
        referencia = boleto.referencia
        ultimo_dia = monthrange(referencia.year, referencia.month)[1]
        no_proprio_mes = referencia.replace(day=min(boleto.contrato.dia_vencimento, ultimo_dia))
        if boleto.vencimento != no_proprio_mes:
            boleto.vencimento = no_proprio_mes
            boleto.save(update_fields=["vencimento"])


class Migration(migrations.Migration):
    dependencies = [
        ("apolices", "0005_sem_pre_ou_pos_pagamento"),
        ("boletos", "0001_inicial"),
    ]

    operations = [migrations.RunPython(vencer_no_proprio_mes, migrations.RunPython.noop)]
