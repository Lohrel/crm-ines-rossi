from django.urls import path

from movimentacoes import views

app_name = "movimentacoes"

urlpatterns = [
    path("", views.MovimentacaoListView.as_view(), name="lista"),
    path(
        "beneficiario/<int:beneficiario_pk>/<str:tipo>/",
        views.MovimentacaoCreateView.as_view(),
        name="nova",
    ),
    path("<int:pk>/", views.MovimentacaoDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.MovimentacaoUpdateView.as_view(), name="editar"),
    path("<int:pk>/etapa/<str:etapa>/", views.MudarEtapaView.as_view(), name="mudar_etapa"),
    path("<int:pk>/refazer/", views.RefazerView.as_view(), name="refazer"),
]
