"""Dialogo con lo SdI tramite PEC: invio delle fatture e lettura della casella.

Regole dal documento ufficiale "Specifiche tecniche operative del SdI" (servizio PEC):
- il primo invio va a sdi01@pec.fatturapa.it; con il primo messaggio di risposta lo SdI
  comunica l'indirizzo da usare per gli invii successivi;
- il file fattura viaggia come allegato del messaggio PEC (limite 30 MB);
- ricevute e notifiche arrivano come file XML allegati, insieme fatture ricevute e metadati.
"""

import email
import imaplib
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as politica_email
from email.utils import parseaddr

from django.db import IntegrityError, transaction
from django.utils import timezone

from anagrafiche.models import Azienda
from fatture.models import Fattura
from fatture.xml import nome_file

from .messaggi import RE_FATTURA, RE_NOTIFICA, leggi_fattura, leggi_notifica
from .models import INDIRIZZO_SDI_INIZIALE, ConfigurazionePEC, FatturaRicevuta, NotificaSdI

log = logging.getLogger(__name__)

RE_MITTENTE_SDI = re.compile(r"^sdi\d+@pec\.fatturapa\.it$", re.IGNORECASE)
TIMEOUT = 30


class ErrorePEC(Exception):
    pass


def configurazione():
    config = ConfigurazionePEC.objects.first()
    if config is None or not config.password_cifrata:
        raise ErrorePEC("Configura prima la casella PEC in Impostazioni PEC.")
    if not config.password:
        raise ErrorePEC("La password PEC salvata non è leggibile (chiave di cifratura cambiata?): reinseriscila.")
    return config


# --- Connessioni -----------------------------------------------------------------

def _smtp(config):
    contesto = ssl.create_default_context()
    if config.smtp_sicurezza == ConfigurazionePEC.Sicurezza.SSL:
        server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_porta, timeout=TIMEOUT, context=contesto)
    else:
        server = smtplib.SMTP(config.smtp_host, config.smtp_porta, timeout=TIMEOUT)
        server.starttls(context=contesto)
    server.login(config.username, config.password)
    return server


def _imap(config):
    contesto = ssl.create_default_context()
    if config.imap_sicurezza == ConfigurazionePEC.Sicurezza.SSL:
        server = imaplib.IMAP4_SSL(config.imap_host, config.imap_porta, ssl_context=contesto, timeout=TIMEOUT)
    else:
        server = imaplib.IMAP4(config.imap_host, config.imap_porta, timeout=TIMEOUT)
        server.starttls(ssl_context=contesto)
    server.login(config.username, config.password)
    return server


def prova_connessione(config):
    """Verifica l'accesso SMTP e IMAP senza inviare nulla. Restituisce un elenco di esiti."""
    esiti = []
    for nome, funzione in (("Invio (SMTP)", _smtp), ("Ricezione (IMAP)", _imap)):
        try:
            server = funzione(config)
            esiti.append((nome, True, "accesso riuscito"))
            try:
                server.quit() if nome.startswith("Invio") else server.logout()
            except Exception:  # noqa: BLE001 - la chiusura non è rilevante per l'esito
                pass
        except Exception as errore:  # noqa: BLE001 - mostriamo all'utente qualunque errore di rete o login
            esiti.append((nome, False, str(errore) or errore.__class__.__name__))
    return esiti


# --- Invio ------------------------------------------------------------------------

def invia_fattura(fattura: Fattura):
    if fattura.stato != Fattura.Stato.EMESSA or not fattura.xml:
        raise ErrorePEC("Si possono inviare solo fatture emesse e non ancora inviate.")
    config = configurazione()
    azienda = Azienda.objects.first()
    nome = nome_file(azienda, fattura.progressivo_invio)

    messaggio = EmailMessage()
    messaggio["From"] = config.indirizzo
    messaggio["To"] = config.indirizzo_sdi
    messaggio["Subject"] = f"Invio file {nome}"
    messaggio.set_content(f"Invio al Sistema di Interscambio del file {nome}.")
    messaggio.add_attachment(fattura.xml.encode("utf-8"), maintype="application", subtype="xml", filename=nome)

    try:
        server = _smtp(config)
        try:
            server.send_message(messaggio)
        finally:
            server.quit()
    except (OSError, smtplib.SMTPException) as errore:
        raise ErrorePEC(f"Invio PEC non riuscito: {errore}") from errore

    fattura.stato = Fattura.Stato.INVIATA
    fattura.inviata_il = timezone.now()
    fattura.save(update_fields=["stato", "inviata_il", "modificata_il"])
    return nome


# --- Lettura ------------------------------------------------------------------------

@dataclass
class EsitoLettura:
    messaggi: int = 0
    notifiche: list = field(default_factory=list)
    fatture_ricevute: list = field(default_factory=list)
    errori: list = field(default_factory=list)
    nuovo_indirizzo_sdi: str = ""


def allegati(messaggio):
    """Tutti gli allegati del messaggio, compresi quelli dentro la busta PEC (postacert.eml)."""
    for parte in messaggio.walk():
        if parte.get_content_type() == "message/rfc822":
            # walk() entra già nei messaggi annidati: basta saltare il contenitore.
            continue
        nome = parte.get_filename()
        if nome and not parte.is_multipart():
            yield nome.strip(), parte.get_payload(decode=True) or b""


def mittente_originale(messaggio):
    """Mittente del messaggio interno alla busta PEC, se presente, altrimenti quello della busta."""
    for parte in messaggio.walk():
        if parte.get_content_type() == "message/rfc822":
            interno = parte.get_payload(0)
            return parseaddr(interno.get("From", ""))[1]
    return parseaddr(messaggio.get("From", ""))[1]


def elabora_messaggio(messaggio, esito: EsitoLettura, config):
    mittente = mittente_originale(messaggio).lower()
    if not RE_MITTENTE_SDI.match(mittente):
        return  # ricevute di accettazione/consegna PEC e posta non dello SdI
    metadati = {}
    file_fatture = []
    for nome, contenuto in allegati(messaggio):
        corrispondenza = RE_NOTIFICA.match(nome)
        if corrispondenza and corrispondenza.group("tipo") == "MT":
            metadati[corrispondenza.group("fattura")] = contenuto
        elif corrispondenza:
            _salva_notifica(nome, contenuto, mittente, esito, config)
        elif RE_FATTURA.match(nome):
            file_fatture.append((nome, contenuto))
    for nome, contenuto in file_fatture:
        base = nome.split(".")[0]
        _salva_fattura_ricevuta(nome, contenuto, metadati.get(base, b""), esito)


def _salva_notifica(nome, contenuto, mittente, esito, config):
    if NotificaSdI.objects.filter(nome_file=nome).exists():
        return
    try:
        dati = leggi_notifica(nome, contenuto)
    except Exception as errore:  # noqa: BLE001 - un file illeggibile non blocca gli altri
        esito.errori.append(f"{nome}: file non leggibile ({errore})")
        return
    progressivo = dati.nome_file_fattura.rsplit("_", 1)[-1]
    fattura = Fattura.objects.filter(progressivo_invio=progressivo, stato__in=[
        Fattura.Stato.INVIATA, Fattura.Stato.CONSEGNATA, Fattura.Stato.NON_RECAPITATA, Fattura.Stato.SCARTATA,
    ]).first()
    with transaction.atomic():
        NotificaSdI.objects.create(
            fattura=fattura, tipo=dati.tipo if dati.tipo in NotificaSdI.Tipo.values else NotificaSdI.Tipo.ALTRO,
            nome_file=nome, nome_file_fattura=dati.nome_file_fattura, identificativo_sdi=dati.identificativo_sdi,
            data_ora=dati.data_ora, errori=dati.errori, xml=dati.xml, mittente=mittente,
        )
        if fattura:
            nuovo_stato = {
                "RC": Fattura.Stato.CONSEGNATA, "MC": Fattura.Stato.NON_RECAPITATA, "NS": Fattura.Stato.SCARTATA,
            }.get(dati.tipo)
            if nuovo_stato:
                fattura.stato = nuovo_stato
            if dati.identificativo_sdi:
                fattura.identificativo_sdi = dati.identificativo_sdi
            fattura.save(update_fields=["stato", "identificativo_sdi", "modificata_il"])
        # Lo SdI risponde dall'indirizzo da usare per i prossimi invii.
        if config.indirizzo_sdi.lower() == INDIRIZZO_SDI_INIZIALE and mittente != INDIRIZZO_SDI_INIZIALE:
            config.indirizzo_sdi = mittente
            config.save(update_fields=["indirizzo_sdi"])
            esito.nuovo_indirizzo_sdi = mittente
    esito.notifiche.append(dati)


def _salva_fattura_ricevuta(nome, contenuto, metadati, esito):
    if FatturaRicevuta.objects.filter(nome_file=nome).exists():
        return
    try:
        dati = leggi_fattura(nome, contenuto)
    except Exception as errore:  # noqa: BLE001
        esito.errori.append(f"{nome}: fattura non leggibile ({errore})")
        return
    identificativo = ""
    if metadati:
        try:
            identificativo = leggi_notifica(nome.split(".")[0] + "_MT_001.xml", metadati).identificativo_sdi
        except Exception:  # noqa: BLE001 - i metadati sono facoltativi per la consultazione
            pass
    try:
        ricevuta = FatturaRicevuta.objects.create(
            nome_file=nome, file_originale=contenuto, xml=dati.xml.decode("utf-8", errors="replace"),
            metadati=metadati.decode("utf-8", errors="replace"), identificativo_sdi=identificativo,
            fornitore=dati.fornitore, fornitore_id_fiscale=dati.fornitore_id_fiscale,
            tipo_documento=dati.tipo_documento, numero=dati.numero, data=dati.data, totale=dati.totale,
            formato=dati.formato,
        )
    except IntegrityError:
        return
    esito.fatture_ricevute.append(ricevuta)


def leggi_casella() -> EsitoLettura:
    """Legge i nuovi messaggi della casella PEC senza segnarli come letti."""
    config = configurazione()
    esito = EsitoLettura()
    try:
        server = _imap(config)
    except (OSError, imaplib.IMAP4.error) as errore:
        raise ErrorePEC(f"Accesso IMAP non riuscito: {errore}") from errore
    try:
        tipo, dati = server.select(f'"{config.imap_cartella}"', readonly=True)
        if tipo != "OK":
            raise ErrorePEC(f"Cartella {config.imap_cartella} non trovata.")
        validity = _uid_validity(server)
        if validity and validity != config.uid_validity:
            # La cartella è cambiata (o è il primo controllo): si rilegge tutto, i doppioni vengono ignorati.
            config.uid_validity, config.ultimo_uid = validity, 0
        _, risposta = server.uid("SEARCH", None, f"UID {config.ultimo_uid + 1}:*")
        uids = [int(u) for u in (risposta[0] or b"").split() if int(u) > config.ultimo_uid]
        for uid in uids:
            _, parti = server.uid("FETCH", str(uid), "(BODY.PEEK[])")
            grezzo = next((p[1] for p in parti if isinstance(p, tuple)), None)
            if grezzo is None:
                continue
            esito.messaggi += 1
            try:
                elabora_messaggio(email.message_from_bytes(grezzo, policy=politica_email), esito, config)
            except Exception as errore:  # noqa: BLE001 - un messaggio problematico non blocca la lettura
                log.exception("Errore nel messaggio PEC %s", uid)
                esito.errori.append(f"Messaggio {uid}: {errore}")
            config.ultimo_uid = uid
    finally:
        try:
            server.logout()
        except Exception:  # noqa: BLE001
            pass
    config.ultimo_controllo = timezone.now()
    config.save(update_fields=["ultimo_uid", "uid_validity", "ultimo_controllo"])
    return esito


def _uid_validity(server):
    risposta = server.response("UIDVALIDITY")[1]
    try:
        return int(risposta[0]) if risposta and risposta[0] else 0
    except (TypeError, ValueError):
        return 0
