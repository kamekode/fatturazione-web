from django.contrib import admin

from .models import Fattura, Incasso, RigaFattura


class IncassoInline(admin.TabularInline):
    model = Incasso
    extra = 0


class RigaInline(admin.TabularInline):
    model = RigaFattura
    extra = 0


@admin.register(Fattura)
class FatturaAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cliente", "stato"]
    inlines = [RigaInline, IncassoInline]
    readonly_fields = ["anno", "numero", "stato", "progressivo_invio", "xml"]
