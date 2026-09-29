from django.apps import AppConfig


class PendenciasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pendencias"
    verbose_name = "Pendências"

    def ready(self) -> None:
        from clientes.historico import LinhaDoTempo
        from pendencias.historico import pendencias_do_cliente

        LinhaDoTempo.registrar_fonte(pendencias_do_cliente)
