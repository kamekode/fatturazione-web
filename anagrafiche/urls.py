from django.urls import path

from . import views

urlpatterns = [
    path("azienda/", views.azienda, name="azienda"),
    path("clienti/", views.clienti, name="clienti"),
    path("clienti/nuovo/", views.cliente_modifica, name="cliente_nuovo"),
    path("clienti/<int:pk>/", views.cliente_modifica, name="cliente_modifica"),
]
