from django.apps import AppConfig


class ApolicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apolices"
    verbose_name = "Seguradoras e contratos"

    def ready(self) -> None:
        from apolices.historico import historico_de_contratos
        from clientes.historico import LinhaDoTempo

        LinhaDoTempo.registrar_fonte(historico_de_contratos)
