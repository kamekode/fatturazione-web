"""Riconoscimento e lettura dei file che arrivano dallo SdI.

Nomenclatura (specifiche tecniche SdI, allegato B, par. 1.1):
- notifiche: <nome file fattura senza estensione>_<tipo>_<progressivo>.xml
  (RC consegna, NS scarto, MC impossibilità di recapito, MT metadati, ...)
- fatture: <paese><id>_<progressivo>.xml oppure .xml.p7m se firmate CAdES
"""

import base64
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from asn1crypto import cms
from lxml import etree

RE_NOTIFICA = re.compile(r"^(?P<fattura>[A-Za-z]{2}[A-Za-z0-9]+_[A-Za-z0-9]{1,5})_(?P<tipo>[A-Z]{2})_(?P<prog>[A-Za-z0-9]{1,3})\.xml$")
RE_FATTURA = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]+_[A-Za-z0-9]{1,5}\.xml(\.p7m)?$", re.IGNORECASE)


def parser_sicuro():
    # File da terzi: niente entità esterne, niente rete.
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def _testo(radice, nome):
    # "{*}" trova l'elemento con o senza namespace.
    el = radice.find(f".//{{*}}{nome}")
    return el.text.strip() if el is not None and el.text else ""


def _tutti(radice, nome):
    return radice.findall(f".//{{*}}{nome}")


@dataclass
class Notifica:
    tipo: str
    nome_file: str
    nome_file_fattura: str
    identificativo_sdi: str
    data_ora: datetime | None
    errori: str
    xml: str


def leggi_notifica(nome_file: str, contenuto: bytes) -> Notifica:
    m = RE_NOTIFICA.match(nome_file)
    radice = etree.fromstring(contenuto, parser_sicuro())
    errori = []
    for errore in _tutti(radice, "Errore"):
        codice, descrizione = _testo(errore, "Codice"), _testo(errore, "Descrizione")
        suggerimento = _testo(errore, "Suggerimento")
        errori.append(" ".join(x for x in [codice, descrizione, f"({suggerimento})" if suggerimento else ""] if x))
    data_testo = _testo(radice, "DataOraConsegna") or _testo(radice, "DataOraRicezione")
    try:
        data_ora = datetime.fromisoformat(data_testo.replace("Z", "+00:00")) if data_testo else None
    except ValueError:
        data_ora = None
    return Notifica(
        tipo=m.group("tipo"),
        nome_file=nome_file,
        nome_file_fattura=m.group("fattura"),
        identificativo_sdi=_testo(radice, "IdentificativoSdI"),
        data_ora=data_ora,
        errori="\n".join(errori),
        xml=contenuto.decode("utf-8", errors="replace"),
    )


def estrai_da_p7m(contenuto: bytes) -> bytes:
    """Estrae l'XML da un file firmato CAdES (.p7m), anche se codificato in base64."""
    # Il DER binario non va ripulito dagli spazi: la firma può terminare con byte come 0x20 o 0x0A.
    dati = contenuto
    if not dati.startswith(b"\x30"):
        dati = base64.b64decode(re.sub(rb"-----[^-]+-----|\s", b"", dati))
    firmato = cms.ContentInfo.load(dati)["content"]
    return firmato["encap_content_info"]["content"].native


@dataclass
class DatiFatturaRicevuta:
    xml: bytes
    formato: str
    fornitore: str
    fornitore_id_fiscale: str
    tipo_documento: str
    numero: str
    data: object
    totale: Decimal | None


def leggi_fattura(nome_file: str, contenuto: bytes) -> DatiFatturaRicevuta:
    xml = estrai_da_p7m(contenuto) if nome_file.lower().endswith(".p7m") else contenuto
    radice = etree.fromstring(xml, parser_sicuro())
    cedente = radice.find(".//{*}CedentePrestatore")
    fornitore, id_fiscale = "", ""
    if cedente is not None:
        fornitore = _testo(cedente, "Denominazione") or f"{_testo(cedente, 'Nome')} {_testo(cedente, 'Cognome')}".strip()
        id_iva = cedente.find(".//{*}IdFiscaleIVA")
        if id_iva is not None:
            id_fiscale = _testo(id_iva, "IdPaese") + _testo(id_iva, "IdCodice")
        else:
            id_fiscale = _testo(cedente, "CodiceFiscale")
    data_testo = _testo(radice, "Data")
    try:
        data = datetime.strptime(data_testo, "%Y-%m-%d").date() if data_testo else None
    except ValueError:
        data = None
    totale_testo = _testo(radice, "ImportoTotaleDocumento")
    try:
        if totale_testo:
            totale = Decimal(totale_testo)
        else:
            # Senza ImportoTotaleDocumento: somma di imponibili e imposte del riepilogo.
            totale = sum(
                (Decimal(_testo(r, "ImponibileImporto") or "0") + Decimal(_testo(r, "Imposta") or "0") for r in _tutti(radice, "DatiRiepilogo")),
                Decimal("0"),
            ) or None
    except InvalidOperation:
        totale = None
    return DatiFatturaRicevuta(
        xml=xml,
        formato=radice.get("versione", ""),
        fornitore=fornitore[:160],
        fornitore_id_fiscale=id_fiscale[:30],
        tipo_documento=_testo(radice, "TipoDocumento")[:4],
        numero=_testo(radice, "Numero")[:20],
        data=data,
        totale=totale,
    )
