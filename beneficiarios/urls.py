from django.urls import path

from beneficiarios import views

app_name = "beneficiarios"

urlpatterns = [
    path("cliente/<int:cliente_pk>/", views.BeneficiarioListView.as_view(), name="lista"),
    path("cliente/<int:cliente_pk>/novo/", views.TitularCreateView.as_view(), name="novo_titular"),
    path("<int:pk>/", views.BeneficiarioDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.BeneficiarioUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.BeneficiarioDeleteView.as_view(), name="excluir"),
    path(
        "<int:titular_pk>/dependentes/novo/",
        views.DependenteCreateView.as_view(),
        name="novo_dependente",
    ),
    path(
        "<int:beneficiario_pk>/planos/novo/", views.VinculoCreateView.as_view(), name="novo_plano"
    ),
    path("planos/<int:pk>/editar/", views.VinculoUpdateView.as_view(), name="editar_plano"),
    path("planos/<int:pk>/excluir/", views.VinculoEncerrarView.as_view(), name="encerrar_plano"),
    path("<int:beneficiario_pk>/anexos/novo/", views.AnexoCreateView.as_view(), name="novo_anexo"),
    path("anexos/<int:pk>/baixar/", views.baixar_anexo, name="baixar_anexo"),
    path("anexos/<int:pk>/excluir/", views.AnexoDeleteView.as_view(), name="excluir_anexo"),
    path(
        "seguro-de-vida/<int:contrato_pk>/",
        views.SeguroDeVidaView.as_view(),
        name="seguro_de_vida",
    ),
    path(
        "seguro-de-vida/<int:contrato_pk>/importar/",
        views.ImportarVidasView.as_view(),
        name="importar_vidas",
    ),
]
