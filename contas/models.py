from django.contrib.auth.models import AbstractUser


class Usuario(AbstractUser):
    """Funcionário da corretora com acesso ao CRM.

    Cada pessoa tem o próprio login, para que o sistema saiba sempre
    quem solicitou e quem realizou cada movimentação.
    """

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["first_name", "last_name", "username"]

    @property
    def nome_exibicao(self) -> str:
        return self.get_full_name() or self.username

    def __str__(self) -> str:
        return self.nome_exibicao
