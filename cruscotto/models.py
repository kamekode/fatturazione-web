from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

PERCENTUALE = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


class ProfiloFiscale(models.Model):
    """Parametri per la stima di imposte e contributi. Esiste un solo record.

    I valori del forfettario vengono dalle istruzioni ufficiali del modello Redditi PF (quadro LM);
    quelli dei contributi INPS cambiano ogni anno e vanno inseriti da chi usa il programma.
    """

    class Gestione(models.TextChoices):
        ARTIGIANI = "artigiani", "INPS artigiani"
        COMMERCIANTI = "commercianti", "INPS commercianti"
        SEPARATA = "separata", "INPS gestione separata"
        NESSUNA = "nessuna", "Nessuna stima (cassa professionale o altro)"

    codice_ateco = models.CharField("codice ATECO", max_length=10, blank=True, default="33.14.00")
    coefficiente_redditivita = models.DecimalField(
        "coefficiente di redditività %", max_digits=5, decimal_places=2, default=Decimal("67"), validators=PERCENTUALE,
        help_text="Allegato 2 alla L. 145/2018 (tabella nelle istruzioni Redditi PF, quadro LM): "
        "67% per \"Altre attività economiche\", che comprende i codici ATECO 33 e 95.",
    )
    aliquota_imposta = models.DecimalField(
        "aliquota imposta sostitutiva %", max_digits=5, decimal_places=2, default=Decimal("15"), validators=PERCENTUALE,
        help_text="15%, oppure 5% per i primi cinque anni di una nuova attività se ricorrono i requisiti.",
    )
    anno_inizio_attivita = models.PositiveIntegerField("anno di inizio attività", null=True, blank=True)
    gestione_previdenziale = models.CharField(max_length=15, choices=Gestione.choices, default=Gestione.ARTIGIANI)
    reddito_minimale = models.DecimalField(
        "reddito minimale INPS", max_digits=12, decimal_places=2, default=Decimal("0"),
        help_text="Artigiani e commercianti: il reddito minimale dell'anno (circolare INPS annuale).",
    )
    contributi_fissi = models.DecimalField(
        "contributi fissi annui", max_digits=12, decimal_places=2, default=Decimal("0"),
        help_text="Artigiani e commercianti: totale annuo dei contributi sul minimale (4 rate).",
    )
    aliquota_contributi = models.DecimalField(
        "aliquota contributi %", max_digits=5, decimal_places=2, default=Decimal("0"), validators=PERCENTUALE,
        help_text="Sul reddito oltre il minimale (artigiani e commercianti) o su tutto il reddito (gestione separata).",
    )
    riduzione_contributiva = models.BooleanField(
        "riduzione contributiva 35% per i forfettari", default=False,
        help_text="Solo se l'hai richiesta all'INPS (artigiani e commercianti).",
    )

    class Meta:
        verbose_name = "profilo fiscale"
        verbose_name_plural = "profilo fiscale"

    def __str__(self):
        return "Profilo fiscale"

    @classmethod
    def corrente(cls):
        return cls.objects.first() or cls()

    def save(self, *args, **kwargs):
        if not self.pk and ProfiloFiscale.objects.exists():
            raise ValidationError("Il profilo fiscale esiste già.")
        super().save(*args, **kwargs)

    @property
    def contributi_configurati(self):
        if self.gestione_previdenziale == self.Gestione.NESSUNA:
            return False
        if self.gestione_previdenziale == self.Gestione.SEPARATA:
            return self.aliquota_contributi > 0
        return self.contributi_fissi > 0 and self.aliquota_contributi > 0


class Versamento(models.Model):
    """Imposte e contributi pagati (F24). Servono per acconti, saldo e deduzione dei contributi."""

    class Tipo(models.TextChoices):
        IMPOSTA_SALDO = "imposta_saldo", "Imposta sostitutiva - saldo"
        IMPOSTA_ACCONTO = "imposta_acconto", "Imposta sostitutiva - acconto"
        CONTRIBUTI_FISSI = "contributi_fissi", "Contributi INPS - fissi"
        CONTRIBUTI_ECCEDENZA = "contributi_eccedenza", "Contributi INPS - a percentuale (saldo o acconto)"
        CONTRIBUTI_ALTRI = "contributi_altri", "Altri contributi previdenziali obbligatori"

    CONTRIBUTI = (Tipo.CONTRIBUTI_FISSI, Tipo.CONTRIBUTI_ECCEDENZA, Tipo.CONTRIBUTI_ALTRI)

    data = models.DateField("data del pagamento", default=timezone.localdate)
    tipo = models.CharField(max_length=25, choices=Tipo.choices)
    anno_riferimento = models.PositiveIntegerField(
        "anno di riferimento", help_text="L'anno d'imposta a cui si riferisce (es. il saldo 2026 pagato a giugno 2027 è del 2026).",
    )
    importo = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name_plural = "versamenti"
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.importo} € del {self.data:%d/%m/%Y}"
