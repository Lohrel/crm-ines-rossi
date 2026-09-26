"""Passa cada contato da unidade para a empresa, mantendo a unidade que ele atendia.

Antes, cada unidade podia ter um contato principal; agora é um por empresa.
Fica como principal o mais antigo entre os que estavam marcados.
"""

from django.db import migrations


def contatos_para_a_empresa(apps, schema_editor):
    Contato = apps.get_model("clientes", "Contato")
    HistoricalContato = apps.get_model("clientes", "HistoricalContato")
    Unidade = apps.get_model("clientes", "Unidade")

    cliente_da_unidade = dict(Unidade.objects.values_list("pk", "cliente_id"))

    principais_por_cliente = {}
    for contato in Contato.objects.filter(principal=True).order_by("pk"):
        cliente_id = cliente_da_unidade[contato.unidade_id]
        if cliente_id in principais_por_cliente:
            Contato.objects.filter(pk=contato.pk).update(principal=False)
        else:
            principais_por_cliente[cliente_id] = contato.pk

    for contato in Contato.objects.all():
        Contato.objects.filter(pk=contato.pk).update(
            cliente_id=cliente_da_unidade[contato.unidade_id]
        )
        contato.unidades.add(contato.unidade_id)

    # Mantém as alterações antigas dos contatos visíveis no histórico da empresa.
    for unidade_id, cliente_id in cliente_da_unidade.items():
        HistoricalContato.objects.filter(unidade_id=unidade_id).update(cliente_id=cliente_id)


def contatos_para_a_unidade(apps, schema_editor):
    Contato = apps.get_model("clientes", "Contato")
    for contato in Contato.objects.all():
        primeira = contato.unidades.order_by("pk").first()
        Contato.objects.filter(pk=contato.pk).update(unidade_id=primeira.pk if primeira else None)


class Migration(migrations.Migration):
    dependencies = [
        ("clientes", "0002_contato_da_empresa_campos"),
    ]

    operations = [
        migrations.RunPython(contatos_para_a_empresa, contatos_para_a_unidade),
    ]
