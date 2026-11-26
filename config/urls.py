from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("", core_views.home, name="home"),
    path("accesso/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("esci/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(success_url="/password/fatto/"),
        name="password_change",
    ),
    path("password/fatto/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("anagrafiche/", include("anagrafiche.urls")),
    path("articoli/", include("catalogo.urls")),
    path("fatture/", include("fatture.urls")),
    path("sdi/", include("sdi.urls")),
    path("importa/", include("migrazione.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
