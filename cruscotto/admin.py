from django.contrib import admin

from .models import ProfiloFiscale, Versamento

admin.site.register(ProfiloFiscale)


@admin.register(Versamento)
class VersamentoAdmin(admin.ModelAdmin):
    list_display = ["data", "tipo", "anno_riferimento", "importo"]
