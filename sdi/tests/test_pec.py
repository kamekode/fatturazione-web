import datetime as dt
from email.message import EmailMessage
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from fatture.models import Fattura
from fatture.servizi import emetti
from fatture.tests.dati import crea_azienda, crea_cliente, crea_fattura
from sdi.messaggi import estrai_da_p7m, leggi_fattura
from sdi.models import ConfigurazionePEC, FatturaRicevuta, NotificaSdI
from sdi.pec import ErrorePEC, invia_fattura, leggi_casella

NS_MSG = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.0"


def ricevuta(tipo, nome_fattura, errori=()):
    lista = "".join(f"<Errore><Codice>{c}</Codice><Descrizione>{d}</Descrizione></Errore>" for c, d in errori)
    extra = f"<ListaErrori>{lista}</ListaErrori>" if errori else "<DataOraConsegna>2026-11-26T10:00:00.000+01:00</DataOraConsegna>"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><ns2:{"RicevutaConsegna" if tipo == "RC" else "NotificaScarto"} '
        f'xmlns:ns2="{NS_MSG}" versione="1.0"><IdentificativoSdI>111222333</IdentificativoSdI>'
        f"<NomeFile>{nome_fattura}.xml</NomeFile><DataOraRicezione>2026-11-26T09:00:00.000+01:00</DataOraRicezione>"
        f"{extra}<MessageId>1</MessageId></ns2:{'RicevutaConsegna' if tipo == 'RC' else 'NotificaScarto'}>"
    ).encode()


def busta_pec(mittente, allegati_interni):
    """Messaggio PEC come lo consegna il gestore: busta con daticert.xml e postacert.eml."""
    interno = EmailMessage()
    interno["From"] = mittente
    interno["To"] = "mario@pec.it"
    interno["Subject"] = "Notifica"
    interno.set_content("Messaggio dello SdI")
    for nome, contenuto in allegati_interni:
        interno.add_attachment(contenuto, maintype="application", subtype="octet-stream", filename=nome)
    busta = EmailMessage()
    busta["From"] = f"Per conto di: {mittente} <posta-certificata@pec.aruba.it>"
    busta["To"] = "mario@pec.it"
    busta["Subject"] = "POSTA CERTIFICATA: Notifica"
    busta.set_content("Messaggio di posta certificata")
    busta.add_attachment(b"<postacert/>", maintype="application", subtype="xml", filename="daticert.xml")
    busta.add_attachment(interno)
    busta.get_payload()[-1].set_param("name", "postacert.eml")
    return busta.as_bytes()


class FintoIMAP:
    def __init__(self, messaggi, validity=7):
        self.messaggi = messaggi  # {uid: bytes}
        self.validity = validity

    def login(self, *a):
        return "OK", []

    def select(self, cartella, readonly=False):
        return "OK", [b"1"]

    def response(self, codice):
        return codice, [str(self.validity).encode()]

    def uid(self, comando, *argomenti):
        if comando == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self.messaggi)).encode()]
        uid = int(argomenti[0])
        return "OK", [(f"{uid} (BODY[] {{1}}".encode(), self.messaggi[uid]), b")"]

    def logout(self):
        pass


def fattura_firmata(xml):
    chiave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fornitore")])
    adesso = dt.datetime.now(dt.timezone.utc)
    certificato = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chiave.public_key())
        .serial_number(1).not_valid_before(adesso).not_valid_after(adesso + dt.timedelta(days=1))
        .sign(chiave, hashes.SHA256())
    )
    return (
        pkcs7.PKCS7SignatureBuilder().set_data(xml).add_signer(certificato, chiave, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )


class BaseSdI(TestCase):
    def setUp(self):
        self.azienda = crea_azienda()
        self.cliente = crea_cliente()
        self.config = ConfigurazionePEC(indirizzo="mario@pec.it", username="mario@pec.it")
        self.config.password = "segreta"
        self.config.save()


class ConfigurazioneTest(BaseSdI):
    def test_password_cifrata(self):
        self.config.refresh_from_db()
        self.assertNotIn("segreta", self.config.password_cifrata)
        self.assertEqual(self.config.password, "segreta")

    def test_valori_aruba_predefiniti(self):
        self.assertEqual((self.config.smtp_host, self.config.smtp_porta), ("smtps.pec.aruba.it", 465))
        self.assertEqual((self.config.imap_host, self.config.imap_porta), ("imaps.pec.aruba.it", 993))
        self.assertEqual(self.config.indirizzo_sdi, "sdi01@pec.fatturapa.it")


class InvioTest(BaseSdI):
    def test_invio_allegato_xml_allo_sdi(self):
        fattura = emetti(crea_fattura(self.cliente))
        with mock.patch("sdi.pec.smtplib.SMTP_SSL") as smtp:
            nome = invia_fattura(fattura)
        server = smtp.return_value
        server.login.assert_called_once_with("mario@pec.it", "segreta")
        messaggio = server.send_message.call_args[0][0]
        self.assertEqual(messaggio["To"], "sdi01@pec.fatturapa.it")
        allegato = next(messaggio.iter_attachments())
        self.assertEqual(allegato.get_filename(), nome)
        self.assertEqual(nome, "ITRSSMRA85T10A562S_00001.xml")
        self.assertIn(b"<ProgressivoInvio>00001</ProgressivoInvio>", allegato.get_content())
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.INVIATA)

    def test_bozza_non_inviabile(self):
        with self.assertRaises(ErrorePEC):
            invia_fattura(crea_fattura(self.cliente))

    def test_errore_smtp_lascia_la_fattura_emessa(self):
        fattura = emetti(crea_fattura(self.cliente))
        with mock.patch("sdi.pec.smtplib.SMTP_SSL", side_effect=OSError("rete assente")):
            with self.assertRaises(ErrorePEC):
                invia_fattura(fattura)
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.EMESSA)


class LetturaTest(BaseSdI):
    def inviata(self):
        fattura = emetti(crea_fattura(self.cliente))
        fattura.stato = Fattura.Stato.INVIATA
        fattura.save()
        return fattura

    def leggi(self, messaggi):
        with mock.patch("sdi.pec.imaplib.IMAP4_SSL", return_value=FintoIMAP(messaggi)):
            return leggi_casella()

    def test_ricevuta_di_consegna(self):
        fattura = self.inviata()
        base = "ITRSSMRA85T10A562S_00001"
        esito = self.leggi({5: busta_pec("sdi12@pec.fatturapa.it", [(f"{base}_RC_001.xml", ricevuta("RC", base))])})
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.CONSEGNATA)
        self.assertEqual(fattura.identificativo_sdi, "111222333")
        self.assertEqual(len(esito.notifiche), 1)
        # Lo SdI ha risposto da sdi12: è l'indirizzo per i prossimi invii.
        self.config.refresh_from_db()
        self.assertEqual(self.config.indirizzo_sdi, "sdi12@pec.fatturapa.it")
        self.assertEqual(self.config.ultimo_uid, 5)
        # Rileggere non duplica nulla.
        self.config.ultimo_uid = 0
        self.config.save()
        self.leggi({5: busta_pec("sdi12@pec.fatturapa.it", [(f"{base}_RC_001.xml", ricevuta("RC", base))])})
        self.assertEqual(NotificaSdI.objects.count(), 1)

    def test_notifica_di_scarto_e_riapertura(self):
        fattura = self.inviata()
        base = "ITRSSMRA85T10A562S_00001"
        xml = ricevuta("NS", base, errori=[("00305", "IdFiscaleIVA del cessionario non valido")])
        self.leggi({1: busta_pec("sdi01@pec.fatturapa.it", [(f"{base}_NS_001.xml", xml)])})
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.SCARTATA)
        self.assertIn("00305", fattura.notifiche.get().errori)

        self.client.force_login(User.objects.create_user("sam", password="x"))
        self.client.post(reverse("fattura_riapri", args=[fattura.pk]))
        fattura.refresh_from_db()
        self.assertEqual((fattura.stato, fattura.numero_documento, fattura.xml), (Fattura.Stato.BOZZA, "1/2026", ""))
        emetti(fattura)
        self.assertEqual(fattura.progressivo_invio, "00002")

    def test_messaggi_non_dello_sdi_ignorati(self):
        self.inviata()
        base = "ITRSSMRA85T10A562S_00001"
        esito = self.leggi({1: busta_pec("truffa@example.com", [(f"{base}_RC_001.xml", ricevuta("RC", base))])})
        self.assertEqual(esito.messaggi, 1)
        self.assertEqual(NotificaSdI.objects.count(), 0)

    def test_fattura_ricevuta_firmata_p7m(self):
        from django.conf import settings

        xml = (settings.SCHEMI_DIR / "IT01234567890_FPR01.xml").read_bytes()
        firmato = fattura_firmata(xml)
        self.assertEqual(estrai_da_p7m(firmato), xml)
        esito = self.leggi({3: busta_pec("sdi20@pec.fatturapa.it", [
            ("IT01234567890_FPR01.xml.p7m", firmato),
            ("IT01234567890_FPR01_MT_001.xml", ricevuta("RC", "IT01234567890_FPR01")),
        ])})
        self.assertEqual(len(esito.fatture_ricevute), 1)
        ricevuta_salvata = FatturaRicevuta.objects.get()
        self.assertEqual(bytes(ricevuta_salvata.file_originale), firmato)
        self.assertEqual(ricevuta_salvata.formato, "FPR12")
        self.assertEqual(ricevuta_salvata.identificativo_sdi, "111222333")
        self.assertTrue(ricevuta_salvata.fornitore)
        self.assertEqual(ricevuta_salvata.numero, leggi_fattura("x.xml", xml).numero)

        self.client.force_login(User.objects.create_user("sam", password="x"))
        risposta = self.client.get(reverse("ricevuta_anteprima", args=[ricevuta_salvata.pk]))
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("default-src 'none'", risposta["Content-Security-Policy"])
        risposta = self.client.get(reverse("ricevuta_file", args=[ricevuta_salvata.pk]))
        self.assertEqual(risposta.content, firmato)

    def test_p7m_in_base64(self):
        import base64

        xml = b"<?xml version='1.0'?><a/>"
        self.assertEqual(estrai_da_p7m(base64.b64encode(fattura_firmata(xml))), xml)

    def test_xml_con_entita_esterne_non_risolte(self):
        malevolo = (
            b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<p:FatturaElettronica xmlns:p='x' versione='FPR12'><Numero>&x;</Numero></p:FatturaElettronica>"
        )
        self.assertNotIn("root", leggi_fattura("IT1_00001.xml", malevolo).numero)


class VisteTest(BaseSdI):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user("sam", password="x"))

    def test_impostazioni_password_non_mostrata_e_mantenuta(self):
        risposta = self.client.get(reverse("impostazioni_pec"))
        self.assertNotContains(risposta, "segreta")
        dati = {
            "indirizzo": "mario@pec.it", "username": "mario@pec.it", "password": "",
            "smtp_host": "smtps.pec.aruba.it", "smtp_porta": 465, "smtp_sicurezza": "ssl",
            "imap_host": "imaps.pec.aruba.it", "imap_porta": 993, "imap_sicurezza": "ssl",
            "imap_cartella": "INBOX", "indirizzo_sdi": "sdi01@pec.fatturapa.it",
        }
        self.client.post(reverse("impostazioni_pec"), dati)
        self.config.refresh_from_db()
        self.assertEqual(self.config.password, "segreta")

    def test_invio_da_pagina(self):
        fattura = emetti(crea_fattura(self.cliente))
        with mock.patch("sdi.pec.smtplib.SMTP_SSL"):
            self.client.post(reverse("fattura_invia", args=[fattura.pk]))
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.INVIATA)

    def test_controlla_pec_senza_configurazione(self):
        ConfigurazionePEC.objects.all().delete()
        risposta = self.client.post(reverse("controlla_pec"), {"torna": "/fatture/"}, follow=True)
        self.assertContains(risposta, "Configura prima la casella PEC")
        self.assertEqual(risposta.redirect_chain[-1][0], "/fatture/")

    def test_controlla_pec_non_reindirizza_fuori(self):
        ConfigurazionePEC.objects.all().delete()
        risposta = self.client.post(reverse("controlla_pec"), {"torna": "//esempio.com"})
        self.assertEqual(risposta["Location"], "/")
