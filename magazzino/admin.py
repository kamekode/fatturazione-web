from django.contrib import admin

from .models import DDT, Movimento, RigaDDT


class RigaDDTInline(admin.TabularInline):
    model = RigaDDT
    extra = 0


@admin.register(DDT)
class DDTAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cliente", "stato", "fattura"]
    inlines = [RigaDDTInline]
    readonly_fields = ["anno", "numero", "stato", "fattura"]


@admin.register(Movimento)
class MovimentoAdmin(admin.ModelAdmin):
    list_display = ["data", "articolo", "tipo", "quantita", "descrizione"]
    list_filter = ["tipo"]
