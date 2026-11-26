from datetime import date
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from lxml import etree

from fatture.calcoli import calcola_totali
from fatture.models import Fattura
from fatture.servizi import emetti
from fatture.xml import (
    NS, ErroreFattura, anteprima_html, genera_xml, nome_file, progressivo_da_numero, schema, valida, versione_schema,
)

from .dati import crea_azienda, crea_cliente, crea_fattura

VERSIONI = ["1.2.3", "1.2.4"]


def testo(xml, percorso):
    albero = etree.fromstring(xml)
    return [e.text for e in albero.iter(percorso)]


class SchemaUfficialeTest(TestCase):
    def test_esempio_ufficiale_fpr01_valido(self):
        # Esempio pubblicato su fatturapa.gov.it: verifica che lo schema si carichi correttamente.
        esempio = settings.SCHEMI_DIR / "IT01234567890_FPR01.xml"
        for versione in VERSIONI:
            self.assertTrue(schema(versione).is_valid(str(esempio)), versione)

    def test_versione_schema_per_data(self):
        self.assertEqual(versione_schema(date(2027, 1, 10)), "1.2.3")
        self.assertEqual(versione_schema(date(2027, 1, 11)), "1.2.4")


class GenerazioneXmlTest(TestCase):
    def setUp(self):
        self.azienda = crea_azienda()
        self.cliente = crea_cliente()

    def assertValido(self, xml):
        for versione in VERSIONI:
            self.assertEqual(valida(xml, versione), [], versione)

    def test_forfettario_con_bollo(self):
        fattura = crea_fattura(self.cliente, righe=[(Decimal("2"), Decimal("50.00"))], causale="Consulenza novembre")
        xml = genera_xml(fattura, self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual(testo(xml, "RegimeFiscale"), ["RF19"])
        self.assertEqual(testo(xml, "Natura"), ["N2.2", "N2.2"])
        self.assertEqual(testo(xml, "BolloVirtuale"), ["SI"])
        self.assertEqual(testo(xml, "ImportoBollo"), ["2.00"])
        self.assertEqual(testo(xml, "ImportoTotaleDocumento"), ["100.00"])
        self.assertEqual(testo(xml, "Imposta"), ["0.00"])
        self.assertEqual(testo(xml, "RiferimentoNormativo"), [self.azienda.riferimento_normativo])
        self.assertEqual(testo(xml, "Numero"), ["1/2026"])
        self.assertEqual(testo(xml, "IBAN"), [self.azienda.iban])
        self.assertEqual(etree.fromstring(xml).tag, f"{{{NS}}}FatturaElettronica")

    def test_sotto_soglia_niente_bollo(self):
        fattura = crea_fattura(self.cliente, righe=[(Decimal("1"), Decimal("77.47"))])
        xml = genera_xml(fattura, self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual(testo(xml, "BolloVirtuale"), [])

    def test_regime_ordinario_con_iva(self):
        self.azienda.regime_fiscale = "RF01"
        fattura = crea_fattura(
            self.cliente,
            righe=[(Decimal("3"), Decimal("10.333333"), Decimal("22"), ""), (Decimal("1"), Decimal("5"), Decimal("22"), "")],
        )
        xml = genera_xml(fattura, self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual(testo(xml, "PrezzoUnitario"), ["10.333333", "5.00"])
        self.assertEqual(testo(xml, "ImponibileImporto"), ["36.00"])
        self.assertEqual(testo(xml, "Imposta"), ["7.92"])
        self.assertEqual(testo(xml, "EsigibilitaIVA"), ["I"])
        self.assertEqual(testo(xml, "ImportoTotaleDocumento"), ["43.92"])

    def test_cliente_privato_con_pec(self):
        cliente = crea_cliente(
            denominazione="", nome="Anna", cognome="Bianchi", partita_iva="",
            codice_fiscale="RSSMRA85T10A562S", codice_destinatario="0000000", pec="anna@pec.example.it",
        )
        xml = genera_xml(crea_fattura(cliente), self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual(testo(xml, "PECDestinatario"), ["anna@pec.example.it"])
        self.assertEqual(testo(xml, "Cognome"), ["Rossi", "Bianchi"])

    def test_cliente_estero(self):
        cliente = crea_cliente(nazione="DE", partita_iva="DE123456789", provincia="", cap="10115", comune="Berlin")
        xml = genera_xml(crea_fattura(cliente), self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual(testo(xml, "CodiceDestinatario"), ["XXXXXXX"])
        self.assertEqual(testo(xml, "IdCodice")[-1], "123456789")

    def test_causale_lunga_divisa_in_blocchi(self):
        fattura = crea_fattura(self.cliente, causale="x" * 450)
        xml = genera_xml(fattura, self.azienda, "00001")
        self.assertValido(xml)
        self.assertEqual([len(c) for c in testo(xml, "Causale")], [200, 200, 50])

    def test_fattura_senza_righe(self):
        fattura = Fattura.objects.create(cliente=self.cliente)
        with self.assertRaises(ErroreFattura):
            genera_xml(fattura, self.azienda, "00001")

    def test_anteprima_con_foglio_di_stile_ufficiale(self):
        xml = genera_xml(crea_fattura(self.cliente), self.azienda, "00001")
        for versione in VERSIONI:
            html = anteprima_html(xml, versione)
            self.assertIn("Cliente Srl", html)
            self.assertIn("1/2026", html)


class EmissioneTest(TestCase):
    def setUp(self):
        self.azienda = crea_azienda()
        self.cliente = crea_cliente()

    def test_emissione_blocca_la_fattura_e_assegna_progressivo(self):
        prima = emetti(crea_fattura(self.cliente))
        seconda = emetti(crea_fattura(self.cliente))
        self.assertEqual(prima.stato, Fattura.Stato.EMESSA)
        self.assertEqual((prima.progressivo_invio, seconda.progressivo_invio), ("00001", "00002"))
        self.assertIn("<ProgressivoInvio>00001</ProgressivoInvio>", prima.xml)
        self.assertEqual(nome_file(self.azienda, prima.progressivo_invio), "ITRSSMRA85T10A562S_00001.xml")
        with self.assertRaises(ErroreFattura):
            emetti(prima)

    def test_numerazione_annuale(self):
        a = crea_fattura(self.cliente, data=date(2026, 12, 31))
        b = crea_fattura(self.cliente, data=date(2026, 12, 31))
        c = crea_fattura(self.cliente, data=date(2027, 1, 2))
        self.assertEqual([a.numero_documento, b.numero_documento, c.numero_documento], ["1/2026", "2/2026", "1/2027"])

    def test_progressivo_base36(self):
        self.assertEqual(progressivo_da_numero(1), "00001")
        self.assertEqual(progressivo_da_numero(36), "00010")
        with self.assertRaises(ErroreFattura):
            progressivo_da_numero(36**5)

    def test_totali_arrotondati(self):
        fattura = crea_fattura(self.cliente, righe=[(Decimal("3"), Decimal("0.335"))])
        self.assertEqual(calcola_totali(fattura.righe.all()).totale_documento, Decimal("1.01"))
