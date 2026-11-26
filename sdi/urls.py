from django.urls import path

from . import views

urlpatterns = [
    path("impostazioni/", views.impostazioni, name="impostazioni_pec"),
    path("controlla/", views.controlla, name="controlla_pec"),
    path("invia/<int:pk>/", views.invia, name="fattura_invia"),
    path("ricevute/", views.ricevute, name="ricevute"),
    path("ricevute/<int:pk>/", views.ricevuta_dettaglio, name="ricevuta_dettaglio"),
    path("ricevute/<int:pk>/anteprima/", views.ricevuta_anteprima, name="ricevuta_anteprima"),
    path("ricevute/<int:pk>/file/", views.ricevuta_file, name="ricevuta_file"),
]
