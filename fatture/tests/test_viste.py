from datetime import date

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
            "cliente": self.cliente.pk, "tipo_documento": "TD01", "data": "2026-11-26", "numero": "1",
            "condizioni_pagamento": "TP02", "modalita_pagamento": "MP05", "termini_pagamento": "30", "data_scadenza": "", "numero_rate": "",
            "rate-TOTAL_FORMS": "0", "rate-INITIAL_FORMS": "0", "rate-MIN_NUM_FORMS": "0", "rate-MAX_NUM_FORMS": "1000",
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

    def test_bollo_a_carico_cliente_dal_modulo(self):
        self.client.post(reverse("fattura_nuova"), self.dati_form(bollo_a_carico_cliente="on"))
        fattura = Fattura.objects.get()
        self.assertTrue(fattura.bollo_a_carico_cliente)
        risposta = self.client.get(reverse("fattura_dettaglio", args=[fattura.pk]))
        self.assertContains(risposta, "502,00 €")
        self.assertContains(risposta, "di cui imposta di bollo a carico del cliente")

    def test_numero_proposto_e_modificabile(self):
        crea_fattura(self.cliente)
        risposta = self.client.get(reverse("fattura_nuova"))
        self.assertEqual(risposta.context["form"].initial["numero"], 2)
        self.client.post(reverse("fattura_nuova"), self.dati_form(numero="10"))
        self.assertEqual(Fattura.objects.get(numero=10).numero_documento, "10/2026")

    def test_numero_duplicato_rifiutato(self):
        crea_fattura(self.cliente)
        risposta = self.client.post(reverse("fattura_nuova"), self.dati_form(numero="1"))
        self.assertContains(risposta, "Esiste già la fattura 1/2026.")
        self.assertEqual(Fattura.objects.count(), 1)

    def test_numero_proposto_segue_l_anno_della_data(self):
        crea_fattura(self.cliente, data=date(2025, 3, 1))
        suggerito = self.client.get(reverse("fattura_nuova")).context["form"].initial["numero"]
        self.client.post(reverse("fattura_nuova"), self.dati_form(data="2025-12-30", numero=str(suggerito)))
        self.assertTrue(Fattura.objects.filter(anno=2025, numero=2).exists())

    def test_scadenza_calcolata_dai_termini(self):
        self.client.post(reverse("fattura_nuova"), self.dati_form(termini_pagamento="30FM"))
        self.assertEqual(Fattura.objects.get().data_scadenza, date(2026, 12, 31))

    def test_data_specifica_obbligatoria(self):
        risposta = self.client.post(reverse("fattura_nuova"), self.dati_form(termini_pagamento="LIBERA"))
        self.assertEqual(risposta.status_code, 200)
        self.assertFalse(Fattura.objects.exists())
        self.client.post(reverse("fattura_nuova"), self.dati_form(termini_pagamento="LIBERA", data_scadenza="2027-02-15"))
        self.assertEqual(Fattura.objects.get().data_scadenza, date(2027, 2, 15))

    def test_rate_generate_dal_numero(self):
        self.client.post(reverse("fattura_nuova"), self.dati_form(condizioni_pagamento="TP01", numero_rate="3"))
        fattura = Fattura.objects.get()
        self.assertIsNone(fattura.data_scadenza)
        self.assertEqual(
            [r.data_scadenza for r in fattura.rate.all()],
            [date(2026, 12, 26), date(2027, 1, 25), date(2027, 2, 24)],
        )
        self.client.post(reverse("fattura_emetti", args=[fattura.pk]))
        fattura.refresh_from_db()
        self.assertEqual(fattura.stato, Fattura.Stato.EMESSA)
        self.assertEqual(fattura.xml.count("<DettaglioPagamento>"), 3)
        self.assertEqual(fattura.xml.count("<ImportoPagamento>166.67</ImportoPagamento>"), 2)
        self.assertIn("<ImportoPagamento>166.66</ImportoPagamento>", fattura.xml)

    def test_rate_inserite_a_mano(self):
        dati = self.dati_form(
            condizioni_pagamento="TP01", numero_rate="",
            **{
                "rate-TOTAL_FORMS": "2",
                "rate-0-data_scadenza": "2027-01-10", "rate-0-importo": "100",
                "rate-1-data_scadenza": "2027-03-10", "rate-1-importo": "",
            },
        )
        self.client.post(reverse("fattura_nuova"), dati)
        fattura = Fattura.objects.get()
        self.assertEqual(fattura.numero_rate, 2)
        risposta = self.client.get(reverse("fattura_dettaglio", args=[fattura.pk]))
        self.assertContains(risposta, "400,00 €")

    def test_una_sola_rata_non_basta(self):
        dati = self.dati_form(
            condizioni_pagamento="TP01", **{"rate-TOTAL_FORMS": "1", "rate-0-data_scadenza": "2027-01-10"}
        )
        risposta = self.client.post(reverse("fattura_nuova"), dati)
        self.assertContains(risposta, "Servono almeno 2 rate.")
        self.assertFalse(Fattura.objects.exists())

    def test_rate_eliminate_se_si_torna_al_pagamento_completo(self):
        self.client.post(reverse("fattura_nuova"), self.dati_form(condizioni_pagamento="TP01", numero_rate="2"))
        fattura = Fattura.objects.get()
        dati = self.dati_form(**{"rate-TOTAL_FORMS": "0", "righe-TOTAL_FORMS": "0", "righe-MIN_NUM_FORMS": "0"})
        riga = fattura.righe.get()
        dati.update({
            "righe-TOTAL_FORMS": "1", "righe-INITIAL_FORMS": "1", "righe-0-id": str(riga.pk), "righe-0-fattura": str(fattura.pk),
        })
        self.client.post(reverse("fattura_modifica", args=[fattura.pk]), dati)
        self.assertEqual(fattura.rate.count(), 0)

    def test_righe_aggiuntive(self):
        dati = self.dati_form(**{
            "righe-TOTAL_FORMS": "6",
            "righe-5-descrizione": "Riga aggiunta", "righe-5-quantita": "1", "righe-5-prezzo_unitario": "10",
            "righe-5-aliquota_iva": "0", "righe-5-natura": "N2.2",
        })
        self.client.post(reverse("fattura_nuova"), dati)
        self.assertEqual(Fattura.objects.get().righe.count(), 2)

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
