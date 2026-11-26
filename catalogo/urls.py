from django.urls import path

from . import views

urlpatterns = [
    path("", views.articoli, name="articoli"),
    path("nuovo/", views.articolo_modifica, name="articolo_nuovo"),
    path("<int:pk>/", views.articolo_modifica, name="articolo_modifica"),
]
