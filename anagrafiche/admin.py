from django.contrib import admin

from .models import Azienda, Cliente

admin.site.register(Azienda)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["__str__", "partita_iva", "codice_fiscale", "codice_destinatario"]
    search_fields = ["denominazione", "cognome", "partita_iva", "codice_fiscale"]
