from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Sum
from django.utils import timezone

from anagrafiche.models import Cliente


def giacenza(articolo, al=None):
    """Somma dei movimenti dell'articolo, eventualmente fino a una data."""
    movimenti = articolo.movimenti.all()
    if al:
        movimenti = movimenti.filter(data__lte=al)
    return movimenti.aggregate(t=Sum("quantita"))["t"] or Decimal("0")


class Movimento(models.Model):
    """Movimento di magazzino. La quantità è positiva per i carichi e negativa per gli scarichi."""

    class Tipo(models.TextChoices):
        CARICO = "carico", "Carico"
        SCARICO = "scarico", "Scarico"
        RETTIFICA = "rettifica", "Rettifica inventario"

    articolo = models.ForeignKey("catalogo.Articolo", on_delete=models.PROTECT, related_name="movimenti")
    data = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    quantita = models.DecimalField("quantità", max_digits=20, decimal_places=4)
    descrizione = models.CharField(max_length=200, blank=True)
    ddt = models.ForeignKey("DDT", on_delete=models.CASCADE, null=True, blank=True, related_name="movimenti")
    fattura = models.ForeignKey("fatture.Fattura", on_delete=models.CASCADE, null=True, blank=True, related_name="movimenti")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "movimenti"
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.quantita} {self.articolo.codice}"


class DDT(models.Model):
    """Documento di trasporto. Numerazione progressiva per anno, separata dalle fatture."""

    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        CONFERMATO = "confermato", "Confermato"

    class Trasporto(models.TextChoices):
        MITTENTE = "mittente", "Mittente"
        DESTINATARIO = "destinatario", "Destinatario"
        VETTORE = "vettore", "Vettore"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ddt")
    anno = models.PositiveIntegerField(editable=False)
    numero = models.PositiveIntegerField(editable=False)
    data = models.DateField(default=timezone.localdate)
    causale_trasporto = models.CharField(
        "causale del trasporto", max_length=100, default="Vendita",
        help_text="Ad esempio Vendita, Reso merce riparata, Conto riparazione, Conto visione.",
    )
    da_fatturare = models.BooleanField(
        default=True, help_text="Togli la spunta per i DDT che non vanno fatturati (ad esempio un reso o un conto riparazione).",
    )
    destinazione = models.TextField(
        "luogo di destinazione", blank=True, help_text="Vuoto = sede del cliente.",
    )
    trasporto_a_cura = models.CharField("trasporto a cura del", max_length=12, choices=Trasporto.choices, default=Trasporto.MITTENTE)
    vettore = models.CharField(max_length=200, blank=True, help_text="Ragione sociale e indirizzo del vettore, se c'è.")
    aspetto_beni = models.CharField("aspetto esteriore dei beni", max_length=100, blank=True, help_text="Ad esempio Scatola, Pallet, Sfuso.")
    numero_colli = models.PositiveIntegerField("numero colli", null=True, blank=True)
    peso_kg = models.DecimalField("peso (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    inizio_trasporto = models.DateTimeField("data e ora inizio trasporto", null=True, blank=True)
    note = models.TextField(blank=True)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.BOZZA, editable=False)
    fattura = models.ForeignKey(
        "fatture.Fattura", on_delete=models.SET_NULL, null=True, blank=True, editable=False, related_name="ddt_fatturati",
    )
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DDT"
        verbose_name_plural = "DDT"
        ordering = ["-anno", "-numero"]
        constraints = [models.UniqueConstraint(fields=["anno", "numero"], name="numero_ddt_unico_per_anno")]

    def __str__(self):
        return f"DDT n. {self.numero_documento} del {self.data:%d/%m/%Y}"

    @property
    def numero_documento(self):
        return f"{self.numero}/{self.anno}"

    @property
    def modificabile(self):
        return self.stato == self.Stato.BOZZA

    @property
    def fatturabile(self):
        return self.stato == self.Stato.CONFERMATO and self.da_fatturare and self.fattura_id is None

    @classmethod
    def prossimo_numero(cls, anno):
        return (cls.objects.filter(anno=anno).aggregate(m=Max("numero"))["m"] or 0) + 1

    def save(self, *args, **kwargs):
        if not self.pk:
            with transaction.atomic():
                self.anno = self.data.year
                if not self.numero:
                    list(DDT.objects.select_for_update().filter(anno=self.anno).values_list("pk"))
                    self.numero = DDT.prossimo_numero(self.anno)
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)


class RigaDDT(models.Model):
    ddt = models.ForeignKey(DDT, on_delete=models.CASCADE, related_name="righe")
    articolo = models.ForeignKey("catalogo.Articolo", on_delete=models.SET_NULL, null=True, blank=True)
    descrizione = models.CharField(max_length=1000)
    quantita = models.DecimalField("quantità", max_digits=20, decimal_places=4, default=Decimal("1"), validators=[MinValueValidator(Decimal("0"))])
    unita_misura = models.CharField("u.m.", max_length=10, blank=True)
    prezzo_unitario = models.DecimalField(
        "prezzo (per la fattura)", max_digits=19, decimal_places=6, null=True, blank=True,
        help_text="Non compare sul DDT stampato: serve per la fattura differita.",
    )
    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name_plural = "righe DDT"

    def __str__(self):
        return self.descrizione[:60]
