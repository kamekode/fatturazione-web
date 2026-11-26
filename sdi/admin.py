from django.contrib import admin

from .models import FatturaRicevuta, NotificaSdI


@admin.register(NotificaSdI)
class NotificaAdmin(admin.ModelAdmin):
    list_display = ["nome_file", "tipo", "fattura", "ricevuta_il"]


@admin.register(FatturaRicevuta)
class FatturaRicevutaAdmin(admin.ModelAdmin):
    list_display = ["fornitore", "numero", "data", "totale"]
    exclude = ["file_originale"]
