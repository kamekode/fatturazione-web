from django.urls import path

from . import views

urlpatterns = [
    path("flextax/", views.importa_flextax, name="importa_flextax"),
]
