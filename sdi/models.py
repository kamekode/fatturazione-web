from django.db import models

from fatture.models import Fattura

from .cifratura import cifra, decifra

INDIRIZZO_SDI_INIZIALE = "sdi01@pec.fatturapa.it"


class ConfigurazionePEC(models.Model):
    """Parametri della casella PEC usata per dialogare con lo SdI. Esiste un solo record.

    I valori predefiniti sono quelli indicati da Aruba per le caselle PEC
    (guide.aruba.it, configurazione programmi di posta).
    """

    class Sicurezza(models.TextChoices):
        SSL = "ssl", "SSL/TLS"
        STARTTLS = "starttls", "STARTTLS"

    indirizzo = models.EmailField("indirizzo PEC")
    username = models.CharField("nome utente", max_length=254, help_text="Di solito l'indirizzo PEC completo.")
    password_cifrata = models.TextField(blank=True, editable=False)
    smtp_host = models.CharField("server SMTP (invio)", max_length=255, default="smtps.pec.aruba.it")
    smtp_porta = models.PositiveIntegerField("porta SMTP", default=465)
    smtp_sicurezza = models.CharField("sicurezza SMTP", max_length=10, choices=Sicurezza.choices, default=Sicurezza.SSL)
    imap_host = models.CharField("server IMAP (ricezione)", max_length=255, default="imaps.pec.aruba.it")
    imap_porta = models.PositiveIntegerField("porta IMAP", default=993)
    imap_sicurezza = models.CharField("sicurezza IMAP", max_length=10, choices=Sicurezza.choices, default=Sicurezza.SSL)
    imap_cartella = models.CharField("cartella da leggere", max_length=100, default="INBOX")
    indirizzo_sdi = models.EmailField(
        "indirizzo PEC dello SdI", default=INDIRIZZO_SDI_INIZIALE,
        help_text="Il primo invio va a sdi01@pec.fatturapa.it. Lo SdI comunica poi l'indirizzo da usare "
        "per i successivi invii (specifiche tecniche SdI, servizio PEC).",
    )
    ultimo_uid = models.PositiveBigIntegerField(default=0, editable=False)
    uid_validity = models.PositiveBigIntegerField(default=0, editable=False)
    ultimo_controllo = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "configurazione PEC"
        verbose_name_plural = "configurazione PEC"

    def __str__(self):
        return self.indirizzo

    @property
    def password(self):
        return decifra(self.password_cifrata)

    @password.setter
    def password(self, valore):
        self.password_cifrata = cifra(valore)


class NotificaSdI(models.Model):
    """Ricevuta o notifica inviata dallo SdI per un file che abbiamo trasmesso."""

    class Tipo(models.TextChoices):
        RC = "RC", "Ricevuta di consegna"
        NS = "NS", "Notifica di scarto"
        MC = "MC", "Mancata consegna"
        NE = "NE", "Notifica di esito"
        DT = "DT", "Decorrenza termini"
        AT = "AT", "Attestazione di trasmissione"
        ALTRO = "--", "Altro"

    fattura = models.ForeignKey(Fattura, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifiche")
    tipo = models.CharField(max_length=2, choices=Tipo.choices)
    nome_file = models.CharField(max_length=100, unique=True)
    nome_file_fattura = models.CharField(max_length=60, db_index=True)
    identificativo_sdi = models.CharField(max_length=20, blank=True)
    data_ora = models.DateTimeField(null=True, blank=True)
    errori = models.TextField(blank=True)
    xml = models.TextField()
    mittente = models.CharField(max_length=254, blank=True)
    ricevuta_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ricevuta_il"]
        verbose_name = "notifica SdI"
        verbose_name_plural = "notifiche SdI"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.nome_file_fattura}"


class FatturaRicevuta(models.Model):
    """Fattura passiva ricevuta tramite lo SdI. Il file originale viene conservato così com'è."""

    nome_file = models.CharField(max_length=100, unique=True)
    file_originale = models.BinaryField()
    xml = models.TextField(help_text="Contenuto XML estratto (senza firma).")
    metadati = models.TextField(blank=True)
    identificativo_sdi = models.CharField(max_length=20, blank=True)
    fornitore = models.CharField(max_length=160, blank=True)
    fornitore_id_fiscale = models.CharField(max_length=30, blank=True)
    tipo_documento = models.CharField(max_length=4, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    data = models.DateField(null=True, blank=True)
    totale = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    formato = models.CharField(max_length=5, blank=True)
    ricevuta_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-ricevuta_il"]
        verbose_name_plural = "fatture ricevute"

    def __str__(self):
        return f"{self.fornitore} n. {self.numero} del {self.data}"
