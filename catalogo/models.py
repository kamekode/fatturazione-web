from decimal import Decimal

from django.db import models

from fatture.codici import Natura


class Articolo(models.Model):
    """Prodotto o servizio da riportare nelle righe di fattura e dei DDT."""

    class Tipo(models.TextChoices):
        BENE = "bene", "Bene"
        SERVIZIO = "servizio", "Servizio"

    codice = models.CharField(max_length=35, unique=True)
    descrizione = models.CharField(max_length=1000)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.SERVIZIO)
    unita_misura = models.CharField("unità di misura", max_length=10, blank=True)
    prezzo = models.DecimalField(max_digits=19, decimal_places=6, default=Decimal("0"))
    aliquota_iva = models.DecimalField("aliquota IVA %", max_digits=5, decimal_places=2, default=Decimal("0"))
    natura = models.CharField(
        max_length=4, choices=Natura.choices, blank=True,
        help_text="Obbligatoria se l'aliquota è 0. Nel forfettario: N2.2.",
    )
    attivo = models.BooleanField(default=True)
    gestito_a_magazzino = models.BooleanField(
        "gestito a magazzino", default=False,
        help_text="Tiene il conto della giacenza: carichi a mano, scarichi automatici con DDT e fatture.",
    )
    scorta_minima = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True,
        help_text="Facoltativa: sotto questa quantità l'articolo viene segnalato nel magazzino.",
    )

    class Meta:
        verbose_name_plural = "articoli"
        ordering = ["codice"]

    def __str__(self):
        return f"{self.codice} - {self.descrizione[:60]}"
