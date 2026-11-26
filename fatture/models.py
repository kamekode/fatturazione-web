from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from anagrafiche.models import Cliente

from .codici import CondizioniPagamento, ModalitaPagamento, Natura, TerminiPagamento, TipoDocumento


class Fattura(models.Model):
    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        EMESSA = "emessa", "Emessa (XML generato)"
        INVIATA = "inviata", "Inviata allo SdI"
        CONSEGNATA = "consegnata", "Consegnata"
        NON_RECAPITATA = "non_recapitata", "Non recapitata (disponibile nel cassetto fiscale)"
        SCARTATA = "scartata", "Scartata dallo SdI"
        IMPORTATA = "importata", "Importata (inviata con un altro programma)"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="fatture")
    tipo_documento = models.CharField(max_length=4, choices=TipoDocumento.choices, default=TipoDocumento.FATTURA)
    anno = models.PositiveIntegerField(editable=False)
    numero = models.PositiveIntegerField(editable=False)
    data = models.DateField(default=timezone.localdate)
    causale = models.TextField(blank=True)
    condizioni_pagamento = models.CharField(max_length=4, choices=CondizioniPagamento.choices, default=CondizioniPagamento.COMPLETO)
    modalita_pagamento = models.CharField(max_length=4, choices=ModalitaPagamento.choices, default=ModalitaPagamento.BONIFICO)
    termini_pagamento = models.CharField(max_length=6, choices=TerminiPagamento.choices, default=TerminiPagamento.GG30)
    data_scadenza = models.DateField(
        "scadenza pagamento", null=True, blank=True,
        help_text="Calcolata in automatico dai termini, salvo con \"Data specifica\".",
    )
    numero_rate = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Solo per il pagamento a rate.")
    bollo_a_carico_cliente = models.BooleanField(
        "bollo a carico del cliente", default=True,
        help_text="Se il bollo è dovuto, i 2 € vengono aggiunti al totale da pagare.",
    )
    stato = models.CharField(max_length=15, choices=Stato.choices, default=Stato.BOZZA, editable=False)
    progressivo_invio = models.CharField(max_length=5, blank=True, editable=False)
    xml = models.TextField(blank=True, editable=False)
    inviata_il = models.DateTimeField(null=True, blank=True, editable=False)
    identificativo_sdi = models.CharField(max_length=20, blank=True, editable=False)
    creata_il = models.DateTimeField(auto_now_add=True)
    modificata_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "fatture"
        ordering = ["-anno", "-numero"]
        constraints = [models.UniqueConstraint(fields=["anno", "numero"], name="numero_unico_per_anno")]

    def __str__(self):
        return f"{self.get_tipo_documento_display()} n. {self.numero_documento} del {self.data:%d/%m/%Y}"

    @property
    def numero_documento(self):
        return f"{self.numero}/{self.anno}"

    @property
    def modificabile(self):
        return self.stato == self.Stato.BOZZA

    def clean(self):
        if self.pk and self.anno and self.data and self.data.year != self.anno:
            raise ValidationError({"data": "Non si può spostare la fattura in un altro anno: la numerazione è annuale."})
        if self.data_scadenza and self.data and self.data_scadenza < self.data:
            raise ValidationError({"data_scadenza": "La scadenza non può precedere la data della fattura."})

    @classmethod
    def prossimo_numero(cls, anno):
        return (cls.objects.filter(anno=anno).aggregate(m=Max("numero"))["m"] or 0) + 1

    def save(self, *args, **kwargs):
        if not self.pk:
            with transaction.atomic():
                self.anno = self.data.year
                if not self.numero:
                    # Blocca le fatture dell'anno per assegnare il numero senza duplicati.
                    list(Fattura.objects.select_for_update().filter(anno=self.anno).values_list("pk"))
                    self.numero = Fattura.prossimo_numero(self.anno)
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)


class RigaFattura(models.Model):
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe")
    articolo = models.ForeignKey("catalogo.Articolo", on_delete=models.SET_NULL, null=True, blank=True)
    descrizione = models.CharField(max_length=1000)
    quantita = models.DecimalField("quantità", max_digits=20, decimal_places=4, default=Decimal("1"), validators=[MinValueValidator(Decimal("0"))])
    unita_misura = models.CharField("u.m.", max_length=10, blank=True)
    prezzo_unitario = models.DecimalField(max_digits=19, decimal_places=6)
    aliquota_iva = models.DecimalField("IVA %", max_digits=5, decimal_places=2, default=Decimal("0"))
    natura = models.CharField(max_length=4, choices=Natura.choices, blank=True)
    ddt = models.ForeignKey(
        "magazzino.DDT", on_delete=models.SET_NULL, null=True, blank=True, related_name="righe_fattura",
        help_text="DDT da cui proviene la riga (fattura differita).",
    )
    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name_plural = "righe fattura"

    def __str__(self):
        return self.descrizione[:60]

    def clean(self):
        if self.aliquota_iva == 0 and not self.natura:
            raise ValidationError({"natura": "Con aliquota 0 va indicata la natura dell'operazione."})
        if self.aliquota_iva and self.aliquota_iva > 0 and self.natura:
            raise ValidationError({"natura": "La natura va indicata solo per le righe senza IVA."})


class Rata(models.Model):
    """Scadenza di una rata (condizioni di pagamento TP01)."""

    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="rate")
    data_scadenza = models.DateField("scadenza")
    importo = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Vuoto = il resto viene diviso in parti uguali tra le rate senza importo.",
    )

    class Meta:
        ordering = ["data_scadenza", "id"]
        verbose_name_plural = "rate"

    def __str__(self):
        return f"Rata del {self.data_scadenza:%d/%m/%Y}"


class Incasso(models.Model):
    """Pagamento ricevuto (anche parziale) per una fattura."""

    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="incassi")
    data = models.DateField()
    importo = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["data", "id"]
        verbose_name_plural = "incassi"

    def __str__(self):
        return f"{self.importo} € del {self.data:%d/%m/%Y}"


class Contatore(models.Model):
    """Contatori progressivi, ad esempio il progressivo di invio dei file allo SdI."""

    nome = models.CharField(max_length=40, unique=True)
    valore = models.PositiveIntegerField(default=0)

    @classmethod
    def prossimo(cls, nome):
        with transaction.atomic():
            contatore, _ = cls.objects.select_for_update().get_or_create(nome=nome)
            contatore.valore += 1
            contatore.save(update_fields=["valore"])
            return contatore.valore
