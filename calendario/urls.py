from django.urls import path

from calendario import views

app_name = "calendario"

urlpatterns = [
    path("", views.CalendarioView.as_view(), name="mes"),
    path("novo/", views.EventoCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.EventoDetailView.as_view(), name="evento"),
    path("<int:pk>/editar/", views.EventoUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.EventoDeleteView.as_view(), name="excluir"),
]
