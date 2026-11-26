from django.urls import path

from . import views

urlpatterns = [
    path("", views.giacenze, name="giacenze"),
    path("articolo/<int:articolo_pk>/", views.movimenti, name="movimenti"),
    path("movimento/nuovo/", views.movimento_nuovo, name="movimento_nuovo"),
    path("ddt/", views.ddt_elenco, name="ddt_elenco"),
    path("ddt/nuovo/", views.ddt_modifica, name="ddt_nuovo"),
    path("ddt/fattura-differita/", views.fattura_differita, name="fattura_differita"),
    path("ddt/<int:pk>/", views.ddt_dettaglio, name="ddt_dettaglio"),
    path("ddt/<int:pk>/modifica/", views.ddt_modifica, name="ddt_modifica"),
    path("ddt/<int:pk>/conferma/", views.ddt_conferma, name="ddt_conferma"),
    path("ddt/<int:pk>/riapri/", views.ddt_riapri, name="ddt_riapri"),
    path("ddt/<int:pk>/elimina/", views.ddt_elimina, name="ddt_elimina"),
    path("ddt/<int:pk>/stampa/", views.ddt_stampa, name="ddt_stampa"),
]
