"""A mudança de contato por unidade para contato da empresa não perde dados."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from clientes.tests.fixtures import CNPJ_FILIAL, CNPJ_MATRIZ

ANTES = [("clientes", "0001_initial")]
DEPOIS = [("clientes", "0004_contato_da_empresa_final")]


def _migrar_para(alvo):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(alvo)
    return executor.loader.project_state(alvo).apps


@pytest.mark.django_db(transaction=True)
def test_contatos_da_unidade_passam_para_a_empresa():
    apps = _migrar_para(ANTES)
    Cliente = apps.get_model("clientes", "Cliente")
    Unidade = apps.get_model("clientes", "Unidade")
    Contato = apps.get_model("clientes", "Contato")
    empresa = Cliente.objects.create(tipo="PJ", nome="Supermercados Exemplo")
    matriz = Unidade.objects.create(
        cliente=empresa, cnpj=CNPJ_MATRIZ, razao_social="Matriz", matriz=True
    )
    filial = Unidade.objects.create(cliente=empresa, cnpj=CNPJ_FILIAL, razao_social="Filial")
    carla = Contato.objects.create(unidade=matriz, nome="Carla", principal=True)
    pedro = Contato.objects.create(unidade=filial, nome="Pedro", principal=True)

    try:
        apps = _migrar_para(DEPOIS)
        Contato = apps.get_model("clientes", "Contato")
        carla = Contato.objects.get(pk=carla.pk)
        pedro = Contato.objects.get(pk=pedro.pk)
        assert carla.cliente_id == pedro.cliente_id == empresa.pk
        assert list(carla.unidades.values_list("pk", flat=True)) == [matriz.pk]
        assert list(pedro.unidades.values_list("pk", flat=True)) == [filial.pk]
        # Só um principal por empresa: fica o mais antigo.
        assert carla.principal and not pedro.principal
    finally:
        _migrar_para(_ultimas_migracoes())


def _ultimas_migracoes():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()
