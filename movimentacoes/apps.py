from django.apps import AppConfig


class MovimentacoesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "movimentacoes"
    verbose_name = "Movimentações"

    def ready(self) -> None:
        from beneficiarios.historico import LinhaDoTempoDoBeneficiario
        from movimentacoes.historico import movimentacoes_da_pessoa

        LinhaDoTempoDoBeneficiario.registrar_fonte(movimentacoes_da_pessoa)
