from django.db import migrations

RAMOS_INICIAIS = ["Vida", "Saúde", "Dental", "Auto", "Imóvel"]


def criar_ramos(apps, schema_editor):
    Ramo = apps.get_model("apolices", "Ramo")
    for nome in RAMOS_INICIAIS:
        Ramo.objects.get_or_create(nome=nome)


class Migration(migrations.Migration):
    dependencies = [("apolices", "0001_initial")]

    operations = [migrations.RunPython(criar_ramos, migrations.RunPython.noop)]
