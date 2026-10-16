from django.urls import path

from clientes import views

app_name = "clientes"

urlpatterns = [
    path("", views.ClienteListView.as_view(), name="lista"),
    path("novo/pessoa-fisica/", views.PessoaFisicaCreateView.as_view(), name="novo_pf"),
    path("novo/empresa/", views.EmpresaCreateView.as_view(), name="nova_empresa"),
    path("<int:pk>/", views.ClienteDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.ClienteDeleteView.as_view(), name="excluir"),
    path(
        "<int:cliente_pk>/unidades/nova/",
        views.UnidadeCreateView.as_view(),
        name="nova_unidade",
    ),
    path("unidades/<int:pk>/editar/", views.UnidadeUpdateView.as_view(), name="editar_unidade"),
    path("unidades/<int:pk>/excluir/", views.UnidadeDeleteView.as_view(), name="excluir_unidade"),
    path(
        "<int:cliente_pk>/contatos/novo/",
        views.ContatoCreateView.as_view(),
        name="novo_contato",
    ),
    path("contatos/<int:pk>/editar/", views.ContatoUpdateView.as_view(), name="editar_contato"),
    path("contatos/<int:pk>/remover/", views.ContatoDeleteView.as_view(), name="remover_contato"),
    path(
        "<int:dono_pk>/documentos/novo/",
        views.DocumentoDoClienteCreateView.as_view(),
        name="novo_documento",
    ),
    path("documentos/<int:pk>/baixar/", views.baixar_documento, name="baixar_documento"),
    path(
        "documentos/<int:pk>/excluir/",
        views.DocumentoDoClienteDeleteView.as_view(),
        name="excluir_documento",
    ),
]
