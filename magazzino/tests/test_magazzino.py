from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from lxml import etree

from catalogo.models import Articolo
from fatture.models import Fattura, RigaFattura
from fatture.servizi import emetti
from fatture.tests.dati import crea_azienda, crea_cliente, crea_fattura
from fatture.xml import valida, versione_schema
from magazzino.models import DDT, Movimento, RigaDDT, giacenza
from magazzino.servizi import (
    ErroreMagazzino, conferma_ddt, crea_fattura_differita, riapri_ddt, termine_fattura_differita,
)


def crea_articolo(**campi):
    dati = dict(codice="MOT1", descrizione="Motore 0,75 kW", tipo="bene", unita_misura="pz", prezzo=Decimal("120"),
                aliquota_iva=Decimal("0"), natura="N2.2", gestito_a_magazzino=True)
    dati.update(campi)
    return Articolo.objects.create(**dati)


def crea_ddt(cliente, righe, **campi):
    ddt = DDT.objects.create(cliente=cliente, data=campi.pop("data", date(2026, 11, 10)), **campi)
    for i, (articolo, quantita, prezzo) in enumerate(righe):
        RigaDDT.objects.create(
            ddt=ddt, articolo=articolo, descrizione=articolo.descrizione if articolo else "Materiale vario",
            quantita=Decimal(quantita), prezzo_unitario=prezzo, ordine=i,
        )
    return ddt


class Base(TestCase):
    def setUp(self):
        self.azienda = crea_azienda()
        self.cliente = crea_cliente()
        self.articolo = crea_articolo()
        Movimento.objects.create(articolo=self.articolo, data=date(2026, 11, 1), tipo="carico", quantita=Decimal("10"))


class DDTTest(Base):
    def test_numerazione_per_anno_separata_dalle_fatture(self):
        crea_fattura(self.cliente)
        primo = crea_ddt(self.cliente, [(self.articolo, "1", None)])
        secondo = crea_ddt(self.cliente, [(self.articolo, "1", None)])
        prossimo_anno = crea_ddt(self.cliente, [(self.articolo, "1", None)], data=date(2027, 1, 5))
        self.assertEqual((primo.numero, secondo.numero, prossimo_anno.numero), (1, 2, 1))

    def test_conferma_scarica_e_riapri_annulla(self):
        ddt = crea_ddt(self.cliente, [(self.articolo, "3", Decimal("120")), (None, "1", Decimal("5"))])
        conferma_ddt(ddt)
        self.assertEqual(giacenza(self.articolo), Decimal("7"))
        self.assertFalse(ddt.modificabile)
        with self.assertRaises(ErroreMagazzino):
            conferma_ddt(ddt)
        riapri_ddt(ddt)
        self.assertEqual(giacenza(self.articolo), Decimal("10"))

    def test_articolo_non_gestito_non_si_muove(self):
        servizio = crea_articolo(codice="RIP", tipo="servizio", gestito_a_magazzino=False)
        conferma_ddt(crea_ddt(self.cliente, [(servizio, "2", None)]))
        self.assertFalse(Movimento.objects.filter(articolo=servizio).exists())

    def test_termine_fattura_differita(self):
        self.assertEqual(termine_fattura_differita(date(2026, 11, 10)), date(2026, 12, 15))
        self.assertEqual(termine_fattura_differita(date(2026, 12, 31)), date(2027, 1, 15))
        self.assertEqual(termine_fattura_differita(date(2027, 1, 31)), date(2027, 2, 15))


class FatturaDifferitaTest(Base):
    def test_fattura_td24_con_dati_ddt_valida(self):
        ddt1 = crea_ddt(self.cliente, [(self.articolo, "2", Decimal("120"))], data=date(2026, 11, 3))
        ddt2 = crea_ddt(self.cliente, [(self.articolo, "1", Decimal("110")), (None, "1", Decimal("15"))], data=date(2026, 11, 20))
        conferma_ddt(ddt1)
        conferma_ddt(ddt2)
        fattura, avvisi = crea_fattura_differita([ddt2, ddt1], date(2026, 11, 30))
        self.assertEqual(avvisi, [])
        self.assertEqual(fattura.tipo_documento, "TD24")
        self.assertEqual(fattura.stato, Fattura.Stato.BOZZA)
        self.assertEqual(fattura.righe.count(), 3)
        self.assertEqual([r.ddt_id for r in fattura.righe.all()], [ddt1.pk, ddt2.pk, ddt2.pk])
        riga_libera = fattura.righe.get(articolo__isnull=True)
        self.assertEqual((riga_libera.aliquota_iva, riga_libera.natura), (Decimal("0"), "N2.2"))
        ddt1.refresh_from_db()
        self.assertEqual(ddt1.fattura, fattura)
        self.assertFalse(ddt1.fatturabile)

        emetti(fattura)
        # Niente doppio scarico: la merce è già uscita con i DDT.
        self.assertEqual(giacenza(self.articolo), Decimal("7"))
        self.assertEqual(valida(fattura.xml.encode(), versione_schema()), [])
        self.assertEqual(valida(fattura.xml.encode(), "1.2.4"), [])
        radice = etree.fromstring(fattura.xml.encode())
        blocchi = radice.findall(".//DatiDDT")
        self.assertEqual([b.findtext("NumeroDDT") for b in blocchi], ["1/2026", "2/2026"])
        self.assertEqual([b.findtext("DataDDT") for b in blocchi], ["2026-11-03", "2026-11-20"])
        self.assertEqual([[e.text for e in b.findall("RiferimentoNumeroLinea")] for b in blocchi], [["1"], ["2", "3"]])

    def test_eliminare_la_bozza_libera_i_ddt(self):
        ddt = crea_ddt(self.cliente, [(self.articolo, "1", Decimal("120"))])
        conferma_ddt(ddt)
        fattura, _ = crea_fattura_differita([ddt], date(2026, 11, 30))
        with self.assertRaises(ErroreMagazzino):
            riapri_ddt(ddt)
        fattura.delete()
        ddt.refresh_from_db()
        self.assertTrue(ddt.fatturabile)

    def test_controlli(self):
        altro = crea_cliente(denominazione="Altro Srl", partita_iva="00743110157")
        bozza = crea_ddt(self.cliente, [(self.articolo, "1", None)])
        with self.assertRaises(ErroreMagazzino):
            crea_fattura_differita([bozza], date(2026, 11, 30))
        a = conferma_ddt(crea_ddt(self.cliente, [(self.articolo, "1", None)]))
        b = conferma_ddt(crea_ddt(altro, [(self.articolo, "1", None)]))
        with self.assertRaises(ErroreMagazzino):
            crea_fattura_differita([a, b], date(2026, 11, 30))
        with self.assertRaises(ErroreMagazzino):
            crea_fattura_differita([a], date(2026, 11, 1))
        non_da_fatturare = conferma_ddt(crea_ddt(self.cliente, [(self.articolo, "1", None)], da_fatturare=False))
        with self.assertRaises(ErroreMagazzino):
            crea_fattura_differita([non_da_fatturare], date(2026, 11, 30))

    def test_avvisi_termine_e_prezzo_mancante(self):
        ddt = conferma_ddt(crea_ddt(self.cliente, [(None, "1", None)], data=date(2026, 10, 1)))
        _, avvisi = crea_fattura_differita([ddt], date(2026, 11, 30))
        self.assertEqual(len(avvisi), 2)
        self.assertIn("15/11/2026", avvisi[0])


class FatturaDirettaTest(Base):
    def test_emissione_scarica_e_riapertura_annulla(self):
        fattura = crea_fattura(self.cliente, righe=[])
        RigaFattura.objects.create(fattura=fattura, articolo=self.articolo, descrizione="Motore", quantita=Decimal("4"),
                                   prezzo_unitario=Decimal("120"), natura="N2.2")
        emetti(fattura)
        self.assertEqual(giacenza(self.articolo), Decimal("6"))
        fattura.stato = Fattura.Stato.SCARTATA
        fattura.save()
        from fatture.servizi import riporta_in_bozza

        riporta_in_bozza(fattura)
        self.assertEqual(giacenza(self.articolo), Decimal("10"))

    def test_nota_di_credito_ricarica(self):
        nota = crea_fattura(self.cliente, righe=[], tipo_documento="TD04")
        RigaFattura.objects.create(fattura=nota, articolo=self.articolo, descrizione="Reso", quantita=Decimal("1"),
                                   prezzo_unitario=Decimal("120"), natura="N2.2")
        emetti(nota)
        self.assertEqual(giacenza(self.articolo), Decimal("11"))


class VisteTest(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user("sam", password="una-password-molto-lunga-42"))

    def test_pagine(self):
        ddt = crea_ddt(self.cliente, [(self.articolo, "1", None)])
        for url in [reverse("giacenze"), reverse("movimenti", args=[self.articolo.pk]), reverse("movimento_nuovo"),
                    reverse("ddt_elenco"), reverse("ddt_nuovo"), reverse("ddt_dettaglio", args=[ddt.pk]),
                    reverse("ddt_modifica", args=[ddt.pk]), reverse("ddt_stampa", args=[ddt.pk]), reverse("fattura_differita")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("ddt_stampa", args=[ddt.pk])), "Documento di trasporto n. 1/2026")

    def test_login_richiesto(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("ddt_elenco")).status_code, 302)

    def test_nuovo_ddt_dal_modulo(self):
        dati = {
            "numero": "1", "data": "2026-11-26", "cliente": self.cliente.pk, "causale_trasporto": "Vendita",
            "da_fatturare": "on", "trasporto_a_cura": "mittente",
            "righe-TOTAL_FORMS": "2", "righe-INITIAL_FORMS": "0", "righe-MIN_NUM_FORMS": "1", "righe-MAX_NUM_FORMS": "1000",
            "righe-0-articolo": self.articolo.pk, "righe-0-quantita": "2",
            "righe-1-quantita": "1",  # riga vuota: ignorata
        }
        risposta = self.client.post(reverse("ddt_nuovo"), dati)
        ddt = DDT.objects.get()
        self.assertRedirects(risposta, reverse("ddt_dettaglio", args=[ddt.pk]))
        riga = ddt.righe.get()
        self.assertEqual((riga.descrizione, riga.prezzo_unitario), ("Motore 0,75 kW", Decimal("120")))
        self.client.post(reverse("ddt_conferma", args=[ddt.pk]))
        self.assertEqual(giacenza(self.articolo), Decimal("8"))

    def test_vettore_obbligatorio(self):
        dati = {"numero": "1", "data": "2026-11-26", "cliente": self.cliente.pk, "causale_trasporto": "Vendita",
                "trasporto_a_cura": "vettore", "righe-TOTAL_FORMS": "1", "righe-INITIAL_FORMS": "0",
                "righe-0-articolo": self.articolo.pk, "righe-0-quantita": "1"}
        self.assertContains(self.client.post(reverse("ddt_nuovo"), dati), "Indica il vettore")

    def test_rettifica_inventario(self):
        self.client.post(reverse("movimento_nuovo"), {"articolo": self.articolo.pk, "data": "2026-11-26", "tipo": "rettifica", "quantita": "8"})
        self.assertEqual(giacenza(self.articolo), Decimal("8"))
        self.client.post(reverse("movimento_nuovo"), {"articolo": self.articolo.pk, "data": "2026-11-26", "tipo": "scarico", "quantita": "3"})
        self.assertEqual(giacenza(self.articolo), Decimal("5"))

    def test_fattura_differita_dalla_pagina(self):
        ddt = conferma_ddt(crea_ddt(self.cliente, [(self.articolo, "1", Decimal("120"))]))
        risposta = self.client.post(reverse("fattura_differita"), {"data": "2026-11-26", "ddt": [ddt.pk]})
        fattura = Fattura.objects.get()
        self.assertRedirects(risposta, reverse("fattura_dettaglio", args=[fattura.pk]))
        self.assertContains(self.client.get(reverse("fattura_dettaglio", args=[fattura.pk])), "n. 1/2026 del")
