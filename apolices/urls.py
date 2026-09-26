from django.urls import path

from apolices import views

app_name = "apolices"

urlpatterns = [
    path("", views.ContratoListView.as_view(), name="contratos"),
    path(
        "cliente/<int:cliente_pk>/novo/", views.ContratoCreateView.as_view(), name="novo_contrato"
    ),
    path("<int:pk>/editar/", views.ContratoUpdateView.as_view(), name="editar_contrato"),
    path("seguradoras/", views.SeguradoraListView.as_view(), name="seguradoras"),
    path("seguradoras/nova/", views.SeguradoraCreateView.as_view(), name="nova_seguradora"),
    path(
        "seguradoras/<int:pk>/editar/",
        views.SeguradoraUpdateView.as_view(),
        name="editar_seguradora",
    ),
]
