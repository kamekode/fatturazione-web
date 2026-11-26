from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from cruscotto.dati import posizioni, riepilogo_mensile
from cruscotto.fisco import RegimeForfettario, RegimeOrdinario, giorno_feriale, piano_acconti, regime_corrente
from cruscotto.models import ProfiloFiscale, Versamento
from fatture.models import Fattura, Incasso, Rata
from fatture.tests.dati import crea_azienda, crea_cliente, crea_fattura

D = Decimal


def emessa(cliente, importo, data, **campi):
    fattura = crea_fattura(cliente, righe=((D("1"), D(importo)),), data=data, **campi)
    fattura.stato = Fattura.Stato.CONSEGNATA
    fattura.save()
    return fattura


class AccontiTest(TestCase):
    def test_soglie(self):
        self.assertEqual(piano_acconti(D("51.65"), 2027), [])
        unico = piano_acconti(D("200"), 2027)
        self.assertEqual([(s.data, s.importo) for s in unico], [(date(2027, 11, 30), D("200.00"))])
        due = piano_acconti(D("1000.01"), 2027)
        self.assertEqual([s.importo for s in due], [D("500.01"), D("500.00")])
        self.assertEqual(due[0].data, date(2027, 6, 30))

    def test_scadenza_nel_fine_settimana(self):
        self.assertEqual(giorno_feriale(date(2029, 6, 30)), date(2029, 7, 2))  # sabato -> lunedì
        self.assertEqual(giorno_feriale(date(2026, 11, 30)), date(2026, 11, 30))


class StimaForfettarioTest(TestCase):
    def setUp(self):
        crea_azienda()
        self.cliente = crea_cliente()

    def test_criterio_di_cassa_e_calcolo(self):
        f1 = emessa(self.cliente, "10000", date(2026, 3, 1))
        f2 = emessa(self.cliente, "5000", date(2026, 12, 1))  # non ancora incassata
        Incasso.objects.create(fattura=f1, data=date(2026, 4, 1), importo=D("10000"))
        f0 = emessa(self.cliente, "2000", date(2025, 12, 20))
        Incasso.objects.create(fattura=f0, data=date(2026, 1, 10), importo=D("2000"))  # fattura 2025 incassata nel 2026
        Versamento.objects.create(data=date(2026, 5, 16), tipo="contributi_fissi", anno_riferimento=2026, importo=D("1000"))
        Versamento.objects.create(data=date(2026, 6, 30), tipo="imposta_acconto", anno_riferimento=2026, importo=D("300"))
        stima = RegimeForfettario(ProfiloFiscale()).stima(2026, oggi=date(2027, 1, 15))
        voci = {v.nome: v.importo for v in stima.voci}
        self.assertEqual(voci["Ricavi incassati"], D("12000"))
        self.assertEqual(voci["Reddito forfettario"], D("8040.00"))  # 67%
        self.assertEqual(voci["Reddito imponibile"], D("7040.00"))
        self.assertEqual(voci["Imposta sostitutiva"], D("1056.00"))  # 15%
        self.assertEqual(voci["Saldo imposta (giugno 2027)"], D("756.00"))
        self.assertEqual([(s.data, s.importo) for s in stima.scadenze], [
            (date(2027, 6, 30), D("756.00")), (date(2027, 6, 30), D("528.00")), (date(2027, 11, 30), D("528.00")),
        ])
        self.assertIn("Contributi non stimati", " ".join(stima.avvisi))
        self.assertTrue(all(v.spiegazione for v in stima.voci))
        self.assertIsNotNone(f2)

    def test_contributi_artigiani_con_riduzione(self):
        f = emessa(self.cliente, "30000", date(2026, 3, 1))
        Incasso.objects.create(fattura=f, data=date(2026, 3, 20), importo=D("30000"))
        profilo = ProfiloFiscale(reddito_minimale=D("18000"), contributi_fissi=D("4400"), aliquota_contributi=D("24"))
        contributi, _ = RegimeForfettario(profilo).contributi_stimati(D("20100"))
        self.assertEqual(contributi, D("4904.00"))  # 4400 + 24% di 2100
        profilo.riduzione_contributiva = True
        contributi, testo = RegimeForfettario(profilo).contributi_stimati(D("20100"))
        self.assertEqual(contributi, D("3187.60"))
        self.assertIn("35%", testo)
        stima = RegimeForfettario(profilo).stima(2026, oggi=date(2026, 11, 26))
        self.assertIn("Contributi INPS 2026 stimati", [v.nome for v in stima.voci])

    def test_gestione_separata(self):
        profilo = ProfiloFiscale(gestione_previdenziale="separata", aliquota_contributi=D("26.07"))
        self.assertEqual(RegimeForfettario(profilo).contributi_stimati(D("10000"))[0], D("2607.00"))

    def test_avviso_soglie_e_aliquota_5(self):
        f = emessa(self.cliente, "90000", date(2026, 3, 1))
        Incasso.objects.create(fattura=f, data=date(2026, 3, 2), importo=D("90000"))
        profilo = ProfiloFiscale(aliquota_imposta=D("5"), anno_inizio_attivita=2020)
        avvisi = " ".join(RegimeForfettario(profilo).stima(2026, oggi=date(2027, 1, 1)).avvisi)
        self.assertIn("dall'anno prossimo", avvisi)
        self.assertIn("primi cinque anni", avvisi)

    def test_nota_di_credito_riduce_i_ricavi(self):
        f = emessa(self.cliente, "1000", date(2026, 3, 1))
        Incasso.objects.create(fattura=f, data=date(2026, 3, 2), importo=D("1000"))
        nc = emessa(self.cliente, "200", date(2026, 3, 5), tipo_documento="TD04")
        Incasso.objects.create(fattura=nc, data=date(2026, 3, 6), importo=D("200"))
        voci = {v.nome: v.importo for v in RegimeForfettario(ProfiloFiscale()).stima(2026).voci}
        self.assertEqual(voci["Ricavi incassati"], D("800"))

    def test_ordinario_non_ancora_disponibile(self):
        from anagrafiche.models import Azienda

        Azienda.objects.update(regime_fiscale="RF01")
        regime = regime_corrente()
        self.assertIsInstance(regime, RegimeOrdinario)
        self.assertFalse(regime.stima(2026).disponibile)


class ScadenzeTest(TestCase):
    def setUp(self):
        crea_azienda()
        self.cliente = crea_cliente()

    def test_rate_coperte_in_ordine(self):
        f = emessa(self.cliente, "300", date(2026, 1, 10), condizioni_pagamento="TP01")
        Rata.objects.create(fattura=f, data_scadenza=date(2026, 2, 10))
        Rata.objects.create(fattura=f, data_scadenza=date(2026, 3, 10))
        Incasso.objects.create(fattura=f, data=date(2026, 2, 9), importo=D("150"))
        p = posizioni()[0]
        self.assertEqual(p.residuo, D("150"))
        self.assertEqual(p.prossima_scadenza.data, date(2026, 3, 10))
        self.assertTrue(p.scaduta(date(2026, 4, 1)))
        self.assertFalse(p.scaduta(date(2026, 3, 1)))

    def test_bozze_e_scartate_escluse(self):
        crea_fattura(self.cliente)
        scartata = crea_fattura(self.cliente, numero=2)
        scartata.stato = Fattura.Stato.SCARTATA
        scartata.save()
        self.assertEqual(posizioni(), [])

    def test_mensile(self):
        f = emessa(self.cliente, "500", date(2026, 3, 1))
        Incasso.objects.create(fattura=f, data=date(2026, 4, 2), importo=D("500"))
        mesi = riepilogo_mensile(2026)
        self.assertEqual((mesi[2]["fatturato"], mesi[3]["incassato"]), (D("500"), D("500")))


class VisteTest(TestCase):
    def setUp(self):
        crea_azienda()
        self.cliente = crea_cliente()
        self.client.force_login(User.objects.create_user("sam", password="una-password-molto-lunga-42"))

    def test_pagine(self):
        f = emessa(self.cliente, "500", date(2026, 3, 1))
        Incasso.objects.create(fattura=f, data=date(2026, 4, 2), importo=D("100"))
        for url in [reverse("cruscotto"), reverse("cruscotto") + "?anno=2026", reverse("scadenziario"),
                    reverse("scadenziario") + "?filtro=scadute", reverse("profilo_fiscale"), reverse("versamenti"),
                    reverse("incasso_nuovo", args=[f.pk]), reverse("fattura_dettaglio", args=[f.pk])]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("cruscotto") + "?anno=2026"), "Imposta sostitutiva")
        self.assertContains(self.client.get(reverse("scadenziario")), "400,00")

    def test_login_richiesto(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("cruscotto")).status_code, 302)

    def test_registra_ed_elimina_incasso(self):
        f = emessa(self.cliente, "500", date(2026, 3, 1))
        risposta = self.client.get(reverse("incasso_nuovo", args=[f.pk]))
        self.assertEqual(risposta.context["form"].initial["importo"], D("500"))
        risposta = self.client.post(reverse("incasso_nuovo", args=[f.pk]), {"data": "2026-04-01", "importo": "500", "torna": "scadenziario"})
        self.assertRedirects(risposta, reverse("scadenziario"))
        incasso = Incasso.objects.get()
        self.client.post(reverse("incasso_elimina", args=[incasso.pk]))
        self.assertFalse(Incasso.objects.exists())

    def test_incasso_su_bozza_rifiutato(self):
        bozza = crea_fattura(self.cliente)
        risposta = self.client.get(reverse("incasso_nuovo", args=[bozza.pk]))
        self.assertRedirects(risposta, reverse("fattura_dettaglio", args=[bozza.pk]))

    def test_profilo_e_versamenti(self):
        self.client.post(reverse("profilo_fiscale"), {
            "codice_ateco": "33.14.00", "coefficiente_redditivita": "67", "aliquota_imposta": "15",
            "gestione_previdenziale": "artigiani", "reddito_minimale": "18000", "contributi_fissi": "4400",
            "aliquota_contributi": "24",
        })
        self.assertTrue(ProfiloFiscale.objects.get().contributi_configurati)
        self.client.post(reverse("versamenti"), {"data": "2026-05-16", "tipo": "contributi_fissi", "anno_riferimento": "2026", "importo": "1100"})
        self.assertEqual(Versamento.objects.count(), 1)
