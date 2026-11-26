"""Generazione e validazione del file XML FatturaPA in formato FPR12 (fattura tra privati).

L'ordine degli elementi segue lo schema ufficiale Schema_VFPR12 (versioni 1.2.3 e 1.2.4).
"""

import string
from datetime import date
from decimal import Decimal
from functools import lru_cache

import xmlschema
from django.conf import settings
from lxml import etree

from .calcoli import NATURA_BOLLO_ADDEBITATO, ErroreRate, calcola_totali, ripartisci_rate, totale_riga

NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Lo schema 1.2.4 (specifiche formato 1.5) vale dall'11 gennaio 2027.
DATA_SCHEMA_1_2_4 = date(2027, 1, 11)
SCHEMI = {"1.2.3": "Schema_VFPR12_v1.2.3.xsd", "1.2.4": "Schema_VFPR12_v1.2.4.xsd"}
FOGLI_DI_STILE = {
    "1.2.3": "Foglio_di_stile_fattura_ordinaria_ver1.2.3.xsl",
    "1.2.4": "Foglio_di_stile_fattura_ordinaria_ver1.2.4.xsl",
}
LUNGHEZZA_CAUSALE = 200
# Riferimento normativo della riga "Imposta di bollo" addebitata al cliente (natura N1),
# preso dalla descrizione del codice N1 nello schema ufficiale di ciascuna versione.
RIFERIMENTO_N1 = {
    "1.2.3": "Escluse ex art. 15 del D.P.R. 633/1972",
    "1.2.4": "Escluse ex art. 29 del D.Lgs. 10/2026",
}


class ErroreFattura(Exception):
    """Dati mancanti o non coerenti che impediscono di generare l'XML."""


def versione_schema(oggi=None):
    oggi = oggi or date.today()
    return "1.2.4" if oggi >= DATA_SCHEMA_1_2_4 else "1.2.3"


@lru_cache(maxsize=None)
def schema(versione):
    return xmlschema.XMLSchema(str(settings.SCHEMI_DIR / SCHEMI[versione]))


def valida(xml_bytes, versione):
    """Restituisce l'elenco degli errori di validazione (vuoto se il file è valido)."""
    return [f"{e.path}: {e.reason}" for e in schema(versione).iter_errors(xml_bytes.decode("utf-8"))]


def _importo(valore: Decimal) -> str:
    return f"{valore.quantize(Decimal('0.01')):.2f}"


def _decimale(valore: Decimal, max_decimali=8) -> str:
    """Numero con almeno 2 e al massimo `max_decimali` decimali, come richiesto dallo schema."""
    testo = f"{valore.quantize(Decimal(1).scaleb(-max_decimali)):f}".rstrip("0")
    intero, _, decimali = testo.partition(".")
    return f"{intero}.{decimali.ljust(2, '0')}"


def _sub(padre, nome, testo=None):
    el = etree.SubElement(padre, nome)
    if testo is not None:
        el.text = str(testo)
    return el


def _opzionale(padre, nome, testo):
    if testo:
        _sub(padre, nome, testo)


def _anagrafica(padre, soggetto):
    anagrafica = _sub(padre, "Anagrafica")
    if soggetto.denominazione:
        _sub(anagrafica, "Denominazione", soggetto.denominazione)
    else:
        _sub(anagrafica, "Nome", soggetto.nome)
        _sub(anagrafica, "Cognome", soggetto.cognome)


def _sede(padre, soggetto, estero=False):
    sede = _sub(padre, "Sede")
    _sub(sede, "Indirizzo", soggetto.indirizzo)
    _opzionale(sede, "NumeroCivico", soggetto.numero_civico)
    _sub(sede, "CAP", "00000" if estero else soggetto.cap)
    _sub(sede, "Comune", soggetto.comune)
    if not estero:
        _opzionale(sede, "Provincia", soggetto.provincia)
    _sub(sede, "Nazione", soggetto.nazione)


def progressivo_da_numero(n: int) -> str:
    """Progressivo di invio alfanumerico di 5 caratteri (base 36)."""
    cifre = string.digits + string.ascii_uppercase
    testo = ""
    while n:
        n, resto = divmod(n, 36)
        testo = cifre[resto] + testo
    if len(testo) > 5:
        raise ErroreFattura("Progressivo di invio esaurito.")
    return testo.rjust(5, "0")


def nome_file(azienda, progressivo):
    return f"IT{azienda.codice_fiscale.upper()}_{progressivo}.xml"


def genera_xml(fattura, azienda, progressivo, versione=None) -> bytes:
    versione = versione or versione_schema()
    righe = list(fattura.righe.select_related("articolo", "ddt"))
    if not righe:
        raise ErroreFattura("La fattura non ha righe.")
    cliente = fattura.cliente
    totali = calcola_totali(righe, fattura.bollo_a_carico_cliente)

    radice = etree.Element(
        f"{{{NS}}}FatturaElettronica",
        nsmap={"p": NS, "ds": NS_DS, "xsi": NS_XSI},
        versione="FPR12",
    )
    radice.set(f"{{{NS_XSI}}}schemaLocation", f"{NS} {SCHEMI['1.2.4']}")

    # --- Header -----------------------------------------------------------
    header = _sub(radice, "FatturaElettronicaHeader")
    trasmissione = _sub(header, "DatiTrasmissione")
    id_trasmittente = _sub(trasmissione, "IdTrasmittente")
    _sub(id_trasmittente, "IdPaese", "IT")
    _sub(id_trasmittente, "IdCodice", azienda.codice_fiscale.upper())
    _sub(trasmissione, "ProgressivoInvio", progressivo)
    _sub(trasmissione, "FormatoTrasmissione", "FPR12")
    _sub(trasmissione, "CodiceDestinatario", cliente.codice_destinatario)
    if cliente.pec and cliente.codice_destinatario == "0000000":
        _sub(trasmissione, "PECDestinatario", cliente.pec)

    cedente = _sub(header, "CedentePrestatore")
    dati = _sub(cedente, "DatiAnagrafici")
    id_iva = _sub(dati, "IdFiscaleIVA")
    _sub(id_iva, "IdPaese", "IT")
    _sub(id_iva, "IdCodice", azienda.partita_iva)
    _sub(dati, "CodiceFiscale", azienda.codice_fiscale.upper())
    _anagrafica(dati, azienda)
    _sub(dati, "RegimeFiscale", azienda.regime_fiscale)
    _sede(cedente, azienda)
    if azienda.telefono or azienda.email:
        contatti = _sub(cedente, "Contatti")
        _opzionale(contatti, "Telefono", azienda.telefono)
        _opzionale(contatti, "Email", azienda.email)

    cessionario = _sub(header, "CessionarioCommittente")
    dati = _sub(cessionario, "DatiAnagrafici")
    if cliente.partita_iva:
        id_iva = _sub(dati, "IdFiscaleIVA")
        if cliente.estero and cliente.partita_iva[:2] == cliente.nazione:
            codice = cliente.partita_iva[2:]
        else:
            codice = cliente.partita_iva
        _sub(id_iva, "IdPaese", cliente.nazione)
        _sub(id_iva, "IdCodice", codice)
    if cliente.codice_fiscale and not cliente.estero:
        _sub(dati, "CodiceFiscale", cliente.codice_fiscale)
    _anagrafica(dati, cliente)
    _sede(cessionario, cliente, estero=cliente.estero)

    # --- Body -------------------------------------------------------------
    body = _sub(radice, "FatturaElettronicaBody")
    generali = _sub(_sub(body, "DatiGenerali"), "DatiGeneraliDocumento")
    _sub(generali, "TipoDocumento", fattura.tipo_documento)
    _sub(generali, "Divisa", "EUR")
    _sub(generali, "Data", fattura.data.isoformat())
    _sub(generali, "Numero", fattura.numero_documento)
    if totali.bollo_virtuale:
        bollo = _sub(generali, "DatiBollo")
        _sub(bollo, "BolloVirtuale", "SI")
        _sub(bollo, "ImportoBollo", _importo(totali.bollo))
    _sub(generali, "ImportoTotaleDocumento", _importo(totali.totale_documento))
    # Causale della fattura e, in coda, il testo a piè di fattura dei dati azienda.
    for testo in (fattura.causale.strip(), azienda.testo_piede.strip()):
        for i in range(0, len(testo), LUNGHEZZA_CAUSALE):
            _sub(generali, "Causale", testo[i : i + LUNGHEZZA_CAUSALE])

    # Fattura differita: riferimenti ai DDT con le linee che vi corrispondono.
    per_ddt = {}
    for numero, riga in enumerate(righe, start=1):
        if riga.ddt_id:
            per_ddt.setdefault(riga.ddt_id, (riga.ddt, []))[1].append(numero)
    for ddt, linee in sorted(per_ddt.values(), key=lambda v: (v[0].data, v[0].anno, v[0].numero)):
        dati_ddt = _sub(generali.getparent(), "DatiDDT")
        _sub(dati_ddt, "NumeroDDT", ddt.numero_documento)
        _sub(dati_ddt, "DataDDT", ddt.data.isoformat())
        for numero in linee:
            _sub(dati_ddt, "RiferimentoNumeroLinea", numero)

    beni = _sub(body, "DatiBeniServizi")
    for numero, riga in enumerate(righe, start=1):
        linea = _sub(beni, "DettaglioLinee")
        _sub(linea, "NumeroLinea", numero)
        if riga.articolo_id:
            codice = _sub(linea, "CodiceArticolo")
            _sub(codice, "CodiceTipo", "INTERNO")
            _sub(codice, "CodiceValore", riga.articolo.codice)
        _sub(linea, "Descrizione", riga.descrizione)
        _sub(linea, "Quantita", _decimale(riga.quantita))
        _opzionale(linea, "UnitaMisura", riga.unita_misura)
        _sub(linea, "PrezzoUnitario", _decimale(riga.prezzo_unitario))
        _sub(linea, "PrezzoTotale", _importo(totale_riga(riga)))
        _sub(linea, "AliquotaIVA", _importo(riga.aliquota_iva))
        _opzionale(linea, "Natura", riga.natura)

    if totali.bollo_addebitato:
        linea = _sub(beni, "DettaglioLinee")
        _sub(linea, "NumeroLinea", len(righe) + 1)
        _sub(linea, "Descrizione", "Imposta di bollo")
        _sub(linea, "Quantita", "1.00")
        _sub(linea, "PrezzoUnitario", _importo(totali.bollo))
        _sub(linea, "PrezzoTotale", _importo(totali.bollo))
        _sub(linea, "AliquotaIVA", "0.00")
        _sub(linea, "Natura", NATURA_BOLLO_ADDEBITATO)

    for r in totali.riepiloghi:
        riepilogo = _sub(beni, "DatiRiepilogo")
        _sub(riepilogo, "AliquotaIVA", _importo(r.aliquota_iva))
        _opzionale(riepilogo, "Natura", r.natura)
        _sub(riepilogo, "ImponibileImporto", _importo(r.imponibile))
        _sub(riepilogo, "Imposta", _importo(r.imposta))
        if r.natura == NATURA_BOLLO_ADDEBITATO and totali.bollo_addebitato:
            _sub(riepilogo, "RiferimentoNormativo", RIFERIMENTO_N1[versione])
        elif r.natura:
            _sub(riepilogo, "RiferimentoNormativo", azienda.riferimento_normativo[:100])
        else:
            _sub(riepilogo, "EsigibilitaIVA", "I")

    pagamento = _sub(body, "DatiPagamento")
    _sub(pagamento, "CondizioniPagamento", fattura.condizioni_pagamento)
    rate = list(fattura.rate.all()) if fattura.condizioni_pagamento == "TP01" else []
    if rate:
        try:
            importi = ripartisci_rate(totali.totale_documento, [r.importo for r in rate])
        except ErroreRate as errore:
            raise ErroreFattura(str(errore)) from errore
        scadenze = list(zip([r.data_scadenza for r in rate], importi))
    else:
        scadenze = [(fattura.data_scadenza, totali.totale_documento)]
    for scadenza, importo in scadenze:
        dettaglio = _sub(pagamento, "DettaglioPagamento")
        _sub(dettaglio, "ModalitaPagamento", fattura.modalita_pagamento)
        if scadenza:
            _sub(dettaglio, "DataScadenzaPagamento", scadenza.isoformat())
        _sub(dettaglio, "ImportoPagamento", _importo(importo))
        if fattura.modalita_pagamento == "MP05" and azienda.iban:
            _opzionale(dettaglio, "IstitutoFinanziario", azienda.istituto_finanziario)
            _sub(dettaglio, "IBAN", azienda.iban)

    return etree.tostring(radice, xml_declaration=True, encoding="UTF-8", pretty_print=True)


@lru_cache(maxsize=None)
def _trasformazione(versione):
    with open(settings.SCHEMI_DIR / FOGLI_DI_STILE[versione], "rb") as f:
        return etree.XSLT(etree.parse(f))


def anteprima_html(xml_bytes, versione) -> str:
    """Applica il foglio di stile ufficiale e restituisce l'HTML della fattura."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    documento = etree.fromstring(xml_bytes, parser)
    return str(_trasformazione(versione)(documento))
