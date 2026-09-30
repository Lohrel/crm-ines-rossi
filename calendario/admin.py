from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from calendario.models import Evento


@admin.register(Evento)
class EventoAdmin(SimpleHistoryAdmin):
    list_display = ["titulo", "tipo", "inicio", "fim", "funcionario", "repete_todo_ano"]
    list_filter = ["tipo", "repete_todo_ano"]
    search_fields = ["titulo"]
    list_select_related = ["funcionario"]
