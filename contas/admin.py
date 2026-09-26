from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from contas.models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ["username", "first_name", "last_name", "email", "is_staff", "is_active"]
