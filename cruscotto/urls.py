from django.urls import path

from . import views

urlpatterns = [
    path("", views.cruscotto, name="cruscotto"),
    path("scadenziario/", views.scadenziario, name="scadenziario"),
    path("profilo-fiscale/", views.profilo, name="profilo_fiscale"),
    path("versamenti/", views.versamenti, name="versamenti"),
    path("versamenti/<int:pk>/elimina/", views.versamento_elimina, name="versamento_elimina"),
    path("fattura/<int:fattura_pk>/incasso/", views.incasso_nuovo, name="incasso_nuovo"),
    path("incasso/<int:pk>/elimina/", views.incasso_elimina, name="incasso_elimina"),
]
