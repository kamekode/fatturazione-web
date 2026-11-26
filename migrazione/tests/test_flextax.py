"""Importazione da Flextax con dati inventati (nessun dato reale nel repository)."""

import io
import zipfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafiche.models import Azienda, Cliente
from fatture.calcoli import calcola_totali
from fatture.models import Contatore, Fattura, Incasso
from fatture.servizi import emetti
from fatture.tests.dati import CF_AZIENDA, PIVA_AZIENDA, crea_azienda
from migrazione.flextax import (
    ErroreImportazione, file_xml_da_zip, importa_fatture, importa_incassi, leggi_csv, leggi_fattura_flextax,
)

NOTA = "Operazione effettuata ai sensi dell'articolo 1, commi da 54 a 89, della Legge n. 190/2014."


def riga_xml(n, descrizione, prezzo, extra=""):
    return f"""<DettaglioLinee><NumeroLinea>{n}</NumeroLinea>{extra}<Descrizione>{descrizione}</Descrizione>
<Quantita>1.00</Quantita><PrezzoUnitario>{prezzo}</PrezzoUnitario><PrezzoTotale>{prezzo}</PrezzoTotale>
<AliquotaIVA>0.00</AliquotaIVA><Natura>N2.2</Natura></DettaglioLinee>"""


def xml_flextax(numero=1, data="2026-03-06", righe=(("Riparazione motore", "300.00"),), bollo="0.00",
                piva_cliente="01234567897", codice_destinatario="ABC1234", pec="", piva_cedente=PIVA_AZIENDA,
                totale=None, pagamenti=None, condizioni="TP02"):
    linee = [riga_xml(i + 1, d, p) for i, (d, p) in enumerate(righe)]
    imponibile = sum(Decimal(p) for _, p in righe) + Decimal(bollo)
    linee.append(riga_xml(len(linee) + 1, "Imposta di bollo assolta in modo virtuale", bollo))
    linee.append(riga_xml(len(linee) + 1, NOTA, "0.00", "<CodiceArticolo><CodiceTipo>NOTA</CodiceTipo><CodiceValore>RIF</CodiceValore></CodiceArticolo>"))
    pagamenti = pagamenti or [("2026-04-06", f"{imponibile:.2f}")]
    dettagli = "".join(
        f"<DettaglioPagamento><ModalitaPagamento>MP05</ModalitaPagamento><DataScadenzaPagamento>{d}</DataScadenzaPagamento>"
        f"<ImportoPagamento>{i}</ImportoPagamento><IBAN>IT60X0542811101000000123456</IBAN></DettaglioPagamento>"
        for d, i in pagamenti
    )
    pec_xml = f"<PECDestinatario>{pec}</PECDestinatario>" if pec else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2" versione="FPR12">
<FatturaElettronicaHeader>
<DatiTrasmissione><IdTrasmittente><IdPaese>IT</IdPaese><IdCodice>{CF_AZIENDA}</IdCodice></IdTrasmittente>
<ProgressivoInvio>{numero}</ProgressivoInvio><FormatoTrasmissione>FPR12</FormatoTrasmissione>
<CodiceDestinatario>{codice_destinatario}</CodiceDestinatario>{pec_xml}</DatiTrasmissione>
<CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{piva_cedente}</IdCodice></IdFiscaleIVA>
<CodiceFiscale>{CF_AZIENDA}</CodiceFiscale><Anagrafica><Denominazione>OFFICINA DI ROSSI MARIO</Denominazione></Anagrafica>
<RegimeFiscale>RF19</RegimeFiscale></DatiAnagrafici>
<Sede><Indirizzo>Via Roma, 1</Indirizzo><CAP>00100</CAP><Comune>Roma</Comune><Provincia>RM</Provincia><Nazione>IT</Nazione></Sede>
</CedentePrestatore>
<CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{piva_cliente}</IdCodice></IdFiscaleIVA>
<Anagrafica><Denominazione>Cliente {piva_cliente} Srl</Denominazione></Anagrafica></DatiAnagrafici>
<Sede><Indirizzo>Via Milano</Indirizzo><NumeroCivico>2</NumeroCivico><CAP>20100</CAP><Comune>Milano</Comune><Provincia>MI</Provincia><Nazione>IT</Nazione></Sede>
</CessionarioCommittente>
</FatturaElettronicaHeader>
<FatturaElettronicaBody>
<DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa><Data>{data}</Data><Numero>{numero}</Numero>
<DatiBollo><BolloVirtuale>SI</BolloVirtuale><ImportoBollo>2.00</ImportoBollo></DatiBollo>
<ImportoTotaleDocumento>{totale or f"{imponibile:.2f}"}</ImportoTotaleDocumento></DatiGeneraliDocumento></DatiGenerali>
<DatiBeniServizi>{"".join(linee)}
<DatiRiepilogo><AliquotaIVA>0.00</AliquotaIVA><Natura>N2.2</Natura><ImponibileImporto>{imponibile:.2f}</ImponibileImporto><Imposta>0.00</Imposta></DatiRiepilogo>
</DatiBeniServizi>
<DatiPagamento><CondizioniPagamento>{condizioni}</CondizioniPagamento>{dettagli}</DatiPagamento>
</FatturaElettronicaBody>
</p:FatturaElettronica>""".encode()


def nome(progressivo):
    return f"IT{CF_AZIENDA}_{progressivo}.xml"


def zip_di(file):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archivio:
        for n, contenuto in file:
            archivio.writestr(n, contenuto)
        archivio.writestr(nome("00020").replace(".xml", ".pdf"), b"%PDF-1.4")
    return buffer.getvalue()


CSV = (
    '﻿Tipo;Numero;Data;Cliente;ATECO;Totale;"Acconto 1";"Data acconto 1";"Acconto 2";"Data acconto 2";'
    '"Acconto 3";"Data acconto 3";"Acconto 4";"Data acconto 4";"Acconto 5";"Data acconto 5";"Acconto 6";'
    '"Data acconto 6";Incassata;TotaleAcconti;Scadenza;Bollo;"Spese anticipate"\n'
    'FT;"=""2""";10/04/2026;"Cliente B";"33.14.00 ";"€ 1.302,00";"€ 1.000,00";2026-05-01;"€ 302,00";2026-05-20;'
    '"€ 0,00";;"€ 0,00";;"€ 0,00";;"€ 0,00";;SI;"€ 1.302,00";10/05/2026;"€ 2,00";"€ 0,00"\n'
    'FT;"=""1""";06/03/2026;"Cliente A";"33.14.00 ";"€ 300,00";"€ 0,00";;"€ 0,00";;"€ 0,00";;"€ 0,00";;'
    '"€ 0,00";;"€ 0,00";;NO;"€ 0,00";06/04/2026;"€ 2,00";"€ 0,00"\n'
    'FT;"=""9""";06/03/2026;"Cliente C";"33.14.00 ";"€ 50,00";"€ 50,00";2026-03-10;"€ 0,00";;"€ 0,00";;"€ 0,00";;'
    '"€ 0,00";;"€ 0,00";;SI;"€ 50,00";06/04/2026;"€ 0,00";"€ 0,00"\n'
).encode("utf-8")


class LetturaTest(TestCase):
    def test_righe_automatiche_di_flextax_non_diventano_righe(self):
        letta = leggi_fattura_flextax(nome("00020"), xml_flextax(bollo="2.00"))
        self.assertEqual([r["descrizione"] for r in letta.righe], ["Riparazione motore"])
        self.assertTrue(letta.bollo_addebitato)
        self.assertEqual(letta.nota, NOTA)
        self.assertEqual(letta.progressivo, "00020")
        self.assertEqual(letta.numero, 1)

    def test_bollo_a_zero_resta_a_carico_dell_emittente(self):
        self.assertFalse(leggi_fattura_flextax(nome("00020"), xml_flextax()).bollo_addebitato)

    def test_nome_file_non_riconosciuto(self):
        with self.assertRaises(ErroreImportazione):
            leggi_fattura_flextax("fattura.xml", xml_flextax())

    def test_entita_esterne_ignorate(self):
        xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
        with self.assertRaises(ErroreImportazione):
            leggi_fattura_flextax(nome("00020"), xml)

    def test_zip_ignora_i_pdf(self):
        file, ignorati = file_xml_da_zip(zip_di([(nome("00020"), xml_flextax())]))
        self.assertEqual([n for n, _ in file], [nome("00020")])
        self.assertEqual(ignorati, 1)

    def test_zip_non_valido(self):
        with self.assertRaises(ErroreImportazione):
            file_xml_da_zip(b"non sono uno zip")

    def test_csv(self):
        documenti = {d["numero"]: d for d in leggi_csv(CSV)}
        self.assertEqual(documenti[2]["acconti"], [(date(2026, 5, 1), Decimal("1000.00")), (date(2026, 5, 20), Decimal("302.00"))])
        self.assertEqual(documenti[1]["acconti"], [])
        self.assertFalse(documenti[1]["incassata"])


class ImportazioneTest(TestCase):
    def file(self):
        return [
            (nome("00020"), xml_flextax(numero=1)),
            (nome("00021"), xml_flextax(
                numero=2, data="2026-04-10", righe=(("Revisione", "1000.00"), ("Ricambi", "300.00")), bollo="2.00",
                piva_cliente="00743110157", codice_destinatario="0000000", pec="cliente@pec.example.it",
            )),
        ]

    def test_importa_azienda_clienti_e_fatture(self):
        resoconto = importa_fatture(self.file())
        self.assertEqual(len(resoconto.importate), 2)
        self.assertTrue(resoconto.azienda_creata)
        self.assertTrue(resoconto.testo_piede_impostato)
        azienda = Azienda.objects.get()
        self.assertEqual(azienda.ragione_sociale, "OFFICINA DI ROSSI MARIO")
        self.assertEqual(azienda.testo_piede, NOTA)
        self.assertEqual(azienda.iban, "IT60X0542811101000000123456")
        azienda.full_clean()

        self.assertEqual(Cliente.objects.count(), 2)
        cliente_pec = Cliente.objects.get(partita_iva="00743110157")
        self.assertEqual((cliente_pec.codice_destinatario, cliente_pec.pec), ("0000000", "cliente@pec.example.it"))
        for cliente in Cliente.objects.all():
            cliente.full_clean()

        fattura = Fattura.objects.get(numero=2, anno=2026)
        self.assertEqual(fattura.stato, Fattura.Stato.IMPORTATA)
        self.assertFalse(fattura.modificabile)
        self.assertTrue(fattura.bollo_a_carico_cliente)
        self.assertEqual(fattura.progressivo_invio, "00021")
        self.assertEqual(fattura.righe.count(), 2)
        self.assertEqual(fattura.data_scadenza, date(2026, 4, 6))
        self.assertEqual(calcola_totali(fattura.righe.all(), True).totale_documento, Decimal("1302.00"))
        self.assertEqual(resoconto.importate[1].avvisi, [])
        self.assertIn("<Numero>2</Numero>", fattura.xml)

    def test_numerazione_e_progressivo_proseguono(self):
        importa_fatture(self.file())
        self.assertEqual(Fattura.prossimo_numero(2026), 3)
        self.assertEqual(Contatore.objects.get(nome="progressivo_invio").valore, int("00021", 36))

    def test_nuova_fattura_non_riusa_il_nome_file(self):
        from fatture.tests.dati import crea_fattura

        importa_fatture(self.file())
        nuova = emetti(crea_fattura(Cliente.objects.first(), data=date(2026, 11, 26)))
        self.assertEqual(nuova.numero, 3)
        self.assertEqual(nuova.progressivo_invio, "00022")

    def test_reimportare_non_duplica(self):
        importa_fatture(self.file())
        resoconto = importa_fatture(self.file())
        self.assertEqual([e.stato for e in resoconto.esiti], ["presente", "presente"])
        self.assertEqual(Fattura.objects.count(), 2)
        self.assertEqual(Cliente.objects.count(), 2)

    def test_numero_gia_usato_da_una_fattura_del_programma(self):
        from fatture.tests.dati import crea_fattura

        crea_azienda()
        cliente = Cliente.objects.create(denominazione="X", partita_iva="01234567897", indirizzo="Via", cap="00100", comune="Roma")
        crea_fattura(cliente, numero=1, data=date(2026, 1, 10))
        resoconto = importa_fatture(self.file())
        self.assertEqual(resoconto.esiti[0].stato, "errore")
        self.assertIn("esiste già", resoconto.esiti[0].messaggio)
        self.assertEqual(resoconto.esiti[1].stato, "importata")

    def test_altra_partita_iva_rifiutata(self):
        crea_azienda()
        resoconto = importa_fatture([(nome("00020"), xml_flextax(piva_cedente="00743110157"))])
        self.assertEqual(resoconto.esiti[0].stato, "errore")
        self.assertEqual(Fattura.objects.count(), 0)

    def test_errore_annulla_anche_il_cliente_creato(self):
        xml = xml_flextax().replace(b"<TipoDocumento>TD01", b"<TipoDocumento>TD16")
        resoconto = importa_fatture([(nome("00020"), xml)])
        self.assertEqual(resoconto.esiti[0].stato, "errore")
        self.assertEqual((Cliente.objects.count(), Azienda.objects.count()), (0, 0))
        self.assertEqual(resoconto.clienti_creati, [])
        self.assertFalse(resoconto.azienda_creata)

    def test_avviso_se_i_totali_non_tornano(self):
        resoconto = importa_fatture([(nome("00020"), xml_flextax(bollo="2.00", totale="300.00"))])
        self.assertIn("diverso dall'importo da pagare", resoconto.esiti[0].avvisi[0])

    def test_pagamento_a_rate(self):
        xml = xml_flextax(condizioni="TP01", pagamenti=[("2026-04-06", "150.00"), ("2026-05-06", "150.00")])
        importa_fatture([(nome("00020"), xml)])
        fattura = Fattura.objects.get()
        self.assertEqual(fattura.numero_rate, 2)
        self.assertEqual([r.importo for r in fattura.rate.all()], [Decimal("150.00"), Decimal("150.00")])

    def test_incassi_dal_csv(self):
        importa_fatture(self.file())
        resoconto = importa_incassi(CSV)
        self.assertEqual(resoconto.incassi_creati, 2)
        self.assertEqual(Incasso.objects.filter(fattura__numero=2).count(), 2)
        self.assertEqual(len(resoconto.avvisi_csv), 1)  # la fattura 9 non è nel programma
        self.assertEqual(importa_incassi(CSV).incassi_creati, 0)


class VistaTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("sam", password="una-password-molto-lunga-42"))

    def test_richiede_login(self):
        self.client.logout()
        risposta = self.client.get(reverse("importa_flextax"))
        self.assertEqual(risposta.status_code, 302)

    def test_caricamento_zip_e_csv(self):
        archivio = SimpleUploadedFile("export.zip", zip_di([(nome("00020"), xml_flextax())]), "application/zip")
        elenco = SimpleUploadedFile("elenco.csv", CSV, "text/csv")
        risposta = self.client.post(reverse("importa_flextax"), {"archivio": archivio, "elenco": elenco})
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Fatture importate: 1")
        self.assertContains(risposta, "La prossima fattura avrà il numero 2/2026")
        fattura = Fattura.objects.get()
        self.assertContains(self.client.get(reverse("fattura_dettaglio", args=[fattura.pk])), "Importata")
        risposta = self.client.get(reverse("fattura_xml", args=[fattura.pk]))
        self.assertIn(f'filename="{nome("00020")}"', risposta["Content-Disposition"])

    def test_eliminare_una_fattura_importata(self):
        importa_fatture([(nome("00020"), xml_flextax())])
        fattura = Fattura.objects.get()
        self.client.post(reverse("fattura_elimina", args=[fattura.pk]))
        self.assertFalse(Fattura.objects.exists())

    def test_nessun_file(self):
        risposta = self.client.post(reverse("importa_flextax"), {})
        self.assertContains(risposta, "Carica almeno un file")
