from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from .validatori import valida_codice_destinatario, valida_codice_fiscale, valida_partita_iva

valida_cap = RegexValidator(r"^\d{5}$", "Il CAP è di 5 cifre.")
valida_provincia = RegexValidator(r"^[A-Z]{2}$", "Sigla della provincia di 2 lettere maiuscole.")
valida_nazione = RegexValidator(r"^[A-Z]{2}$", "Codice nazione ISO di 2 lettere (es. IT).")


class RegimeFiscale(models.TextChoices):
    # Codici dello schema FatturaPA (elemento RegimeFiscale).
    ORDINARIO = "RF01", "RF01 - Ordinario"
    MINIMI = "RF02", "RF02 - Contribuenti minimi"
    FORFETTARIO = "RF19", "RF19 - Forfettario"


# Testo modificabile dalla pagina "Dati azienda". Da verificare quando entrerà in vigore
# il nuovo riferimento normativo indicato nello schema 1.2.4 (D.Lgs. 117/2026).
RIFERIMENTO_FORFETTARIO_PREDEFINITO = (
    "Operazione in franchigia da IVA ai sensi dell'art. 1, commi 54-89, L. 190/2014"
)


class Sede(models.Model):
    indirizzo = models.CharField(max_length=60)
    numero_civico = models.CharField(max_length=8, blank=True)
    cap = models.CharField("CAP", max_length=5, validators=[valida_cap])
    comune = models.CharField(max_length=60)
    provincia = models.CharField(max_length=2, blank=True, validators=[valida_provincia])
    nazione = models.CharField(max_length=2, default="IT", validators=[valida_nazione])

    class Meta:
        abstract = True


class Azienda(Sede):
    """I dati di chi emette le fatture (il cedente/prestatore). Esiste un solo record."""

    denominazione = models.CharField(max_length=80, blank=True, help_text="Per le società. Per una ditta individuale lasciare vuoto e compilare nome e cognome.")
    nome = models.CharField(max_length=60, blank=True)
    cognome = models.CharField(max_length=60, blank=True)
    partita_iva = models.CharField("Partita IVA", max_length=11, validators=[valida_partita_iva])
    codice_fiscale = models.CharField(max_length=16, validators=[valida_codice_fiscale])
    regime_fiscale = models.CharField(max_length=4, choices=RegimeFiscale.choices, default=RegimeFiscale.FORFETTARIO)
    riferimento_normativo = models.CharField(
        max_length=100,
        default=RIFERIMENTO_FORFETTARIO_PREDEFINITO,
        help_text="Testo inserito nel riepilogo delle righe senza IVA (max 100 caratteri, limite dello schema).",
    )
    testo_piede = models.TextField(
        "testo a piè di fattura", blank=True,
        help_text="Testo libero (es. altri riferimenti normativi) aggiunto in fondo a ogni fattura. "
        "Nell'XML viene inserito nella Causale.",
    )
    telefono = models.CharField(max_length=12, blank=True)
    email = models.EmailField(blank=True)
    pec = models.EmailField("PEC", blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    istituto_finanziario = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = "dati azienda"
        verbose_name_plural = "dati azienda"

    def __str__(self):
        return self.ragione_sociale

    @property
    def ragione_sociale(self):
        return self.denominazione or f"{self.nome} {self.cognome}".strip()

    @property
    def forfettario(self):
        return self.regime_fiscale == RegimeFiscale.FORFETTARIO

    def clean(self):
        if not self.denominazione and not (self.nome and self.cognome):
            raise ValidationError("Indicare la denominazione oppure nome e cognome.")
        self.codice_fiscale = self.codice_fiscale.upper()
        self.iban = self.iban.replace(" ", "").upper()

    def save(self, *args, **kwargs):
        if not self.pk and Azienda.objects.exists():
            raise ValidationError("I dati azienda esistono già: modificare quelli presenti.")
        super().save(*args, **kwargs)


class Cliente(Sede):
    denominazione = models.CharField(max_length=80, blank=True)
    nome = models.CharField(max_length=60, blank=True)
    cognome = models.CharField(max_length=60, blank=True)
    partita_iva = models.CharField("Partita IVA / ID fiscale", max_length=28, blank=True)
    codice_fiscale = models.CharField(max_length=16, blank=True)
    codice_destinatario = models.CharField(
        max_length=7,
        default="0000000",
        validators=[valida_codice_destinatario],
        help_text="Codice SDI di 7 caratteri. 0000000 se il cliente non lo ha comunicato (eventualmente con la PEC).",
    )
    pec = models.EmailField("PEC destinatario", blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "clienti"
        ordering = ["denominazione", "cognome", "nome"]

    def __str__(self):
        return self.ragione_sociale

    @property
    def ragione_sociale(self):
        return self.denominazione or f"{self.nome} {self.cognome}".strip()

    @property
    def estero(self):
        return self.nazione != "IT"

    def clean(self):
        errori = {}
        if not self.denominazione and not (self.nome and self.cognome):
            errori["denominazione"] = "Indicare la denominazione oppure nome e cognome."
        self.codice_fiscale = self.codice_fiscale.upper()
        self.partita_iva = self.partita_iva.replace(" ", "").upper()
        self.codice_destinatario = self.codice_destinatario.upper()
        if self.estero:
            # Per i clienti esteri lo SdI prevede il codice destinatario XXXXXXX.
            self.codice_destinatario = "XXXXXXX"
            if not self.partita_iva:
                errori["partita_iva"] = "Per un cliente estero indicare l'identificativo fiscale."
        else:
            if not self.partita_iva and not self.codice_fiscale:
                errori["codice_fiscale"] = "Indicare almeno la partita IVA o il codice fiscale."
            if self.partita_iva:
                try:
                    valida_partita_iva(self.partita_iva)
                except ValidationError as e:
                    errori["partita_iva"] = e.messages
            if self.codice_fiscale:
                try:
                    valida_codice_fiscale(self.codice_fiscale)
                except ValidationError as e:
                    errori["codice_fiscale"] = e.messages
        if errori:
            raise ValidationError(errori)
