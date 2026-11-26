from django.urls import path

from . import views

urlpatterns = [
    path("", views.elenco, name="fatture"),
    path("nuova/", views.modifica, name="fattura_nuova"),
    path("<int:pk>/", views.dettaglio, name="fattura_dettaglio"),
    path("<int:pk>/modifica/", views.modifica, name="fattura_modifica"),
    path("<int:pk>/emetti/", views.emissione, name="fattura_emetti"),
    path("<int:pk>/elimina/", views.elimina, name="fattura_elimina"),
    path("<int:pk>/riapri/", views.riapri, name="fattura_riapri"),
    path("<int:pk>/xml/", views.scarica_xml, name="fattura_xml"),
    path("<int:pk>/anteprima/", views.anteprima, name="fattura_anteprima"),
]
