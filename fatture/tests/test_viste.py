from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafiche.validatori import codice_fiscale_persona_valido, partita_iva_valida
from fatture.models import Fattura

from .dati import crea_azienda, crea_cliente, crea_fattura

PASSWORD = "una-password-molto-lunga-42"


class SicurezzaTest(TestCase):
    def setUp(self):
        self.utente = User.objects.create_user("sam", password=PASSWORD)

    def test_pagine_protette_da_login(self):
        crea_azienda()
        fattura = crea_fattura(crea_cliente())
        pagine = [
            reverse("home"), reverse("fatture"), reverse("fattura_nuova"), reverse("clienti"), reverse("articoli"),
            reverse("azienda"), reverse("fattura_dettaglio", args=[fattura.pk]), reverse("fattura_anteprima", args=[fattura.pk]),
            reverse("fattura_xml", args=[fattura.pk]),
        ]
        for url in pagine:
            risposta = self.client.get(url)
            self.assertEqual(risposta.status_code, 302, url)
            self.assertTrue(risposta["Location"].startswith(reverse("login")), url)

    def test_accesso_e_intestazioni(self):
        risposta = self.client.post(reverse("login"), {"username": "sam", "password": PASSWORD})
        self.assertRedirects(risposta, reverse("home"), fetch_redirect_response=False)
        risposta = self.client.get(reverse("home"))
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("default-src 'self'", risposta["Content-Security-Policy"])
        self.assertEqual(risposta["X-Frame-Options"], "DENY")
        self.assertIn("no-store", risposta["Cache-Control"])

    def test_blocco_dopo_tentativi_falliti(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "sam", "password": "sbagliata"})
        risposta = self.client.post(reverse("login"), {"username": "sam", "password": PASSWORD})
        self.assertEqual(risposta.status_code, 429)
        self.assertContains(risposta, "temporaneamente bloccato", status_code=429)

    def test_logout_solo_post(self):
        self.client.force_login(self.utente)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)


class FlussoFatturaTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("sam", password=PASSWORD))
        self.azienda = crea_azienda()
        self.cliente = crea_cliente()

    def dati_form(self, **extra):
        dati = {
            "cliente": self.cliente.pk, "tipo_documento": "TD01", "data": "2026-11-26", "causale": "",
            "condizioni_pagamento": "TP02", "modalita_pagamento": "MP05", "data_scadenza": "2026-12-26",
            "righe-TOTAL_FORMS": "2", "righe-INITIAL_FORMS": "0", "righe-MIN_NUM_FORMS": "1", "righe-MAX_NUM_FORMS": "1000",
            "righe-0-descrizione": "Sviluppo sito", "righe-0-quantita": "1", "righe-0-prezzo_unitario": "500",
            "righe-0-aliquota_iva": "0", "righe-0-natura": "N2.2",
        }
        dati.update(extra)
        return dati

    def test_crea_emetti_e_scarica(self):
        risposta = self.client.post(reverse("fattura_nuova"), self.dati_form())
        fattura = Fattura.objects.get()
        self.assertRedirects(risposta, reverse("fattura_dettaglio", args=[fattura.pk]))
        self.assertEqual(fattura.righe.count(), 1)

        self.client.post(reverse("fattura_emetti", args=[fattura.pk]))
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.EMESSA)

        risposta = self.client.get(reverse("fattura_xml", args=[fattura.pk]))
        self.assertEqual(risposta["Content-Disposition"], 'attachment; filename="ITRSSMRA85T10A562S_00001.xml"')
        self.assertIn(b"<Natura>N2.2</Natura>", risposta.content)

        # Una fattura emessa non è più modificabile.
        risposta = self.client.post(reverse("fattura_modifica", args=[fattura.pk]), self.dati_form())
        self.assertRedirects(risposta, reverse("fattura_dettaglio", args=[fattura.pk]))

    def test_riga_senza_natura_con_aliquota_zero(self):
        risposta = self.client.post(reverse("fattura_nuova"), self.dati_form(**{"righe-0-natura": ""}))
        self.assertEqual(risposta.status_code, 200)
        self.assertFalse(Fattura.objects.exists())

    def test_anteprima_ha_politica_restrittiva(self):
        fattura = crea_fattura(self.cliente)
        risposta = self.client.get(reverse("fattura_anteprima", args=[fattura.pk]))
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("default-src 'none'", risposta["Content-Security-Policy"])


class ValidatoriTest(TestCase):
    def test_partita_iva(self):
        self.assertTrue(partita_iva_valida("12345678903"))
        self.assertFalse(partita_iva_valida("12345678900"))
        self.assertFalse(partita_iva_valida("1234567890"))

    def test_codice_fiscale(self):
        self.assertTrue(codice_fiscale_persona_valido("RSSMRA85T10A562S"))
        self.assertFalse(codice_fiscale_persona_valido("RSSMRA85T10A562X"))
