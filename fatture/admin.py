from django.contrib import admin

from .models import Fattura, RigaFattura


class RigaInline(admin.TabularInline):
    model = RigaFattura
    extra = 0


@admin.register(Fattura)
class FatturaAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cliente", "stato"]
    inlines = [RigaInline]
    readonly_fields = ["anno", "numero", "stato", "progressivo_invio", "xml"]
