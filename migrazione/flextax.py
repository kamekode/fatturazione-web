"""Importazione dei dati esportati da Flextax.

Flextax esporta:
- uno ZIP con le fatture emesse in formato FatturaPA (XML, eventualmente .p7m) più i PDF;
- un CSV (separatore ";") con l'elenco documenti, i totali e fino a 6 acconti incassati.

Gli XML sono la fonte principale: contengono cliente, righe e pagamento. Il CSV serve solo
per gli incassi. Le fatture importate restano in sola lettura con lo stato "importata".
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from lxml import etree

from anagrafiche.models import Azienda, Cliente, RegimeFiscale
from fatture.calcoli import calcola_totali
from fatture.codici import CondizioniPagamento, ModalitaPagamento, Natura, TerminiPagamento, TipoDocumento
from fatture.models import Contatore, Fattura, Incasso, Rata, RigaFattura
from sdi.messaggi import estrai_da_p7m, parser_sicuro

# Nome file: IT<codice fiscale>_<progressivo>.xml[.p7m]
RE_NOME = re.compile(r"^[A-Z]{2}[A-Z0-9]+_(?P<prog>[A-Z0-9]{1,5})\.xml(\.p7m)?$", re.IGNORECASE)

# Limiti contro archivi anomali.
MAX_FILE_NELLO_ZIP = 5000
MAX_DIMENSIONE_FILE = 5 * 1024 * 1024
MAX_DIMENSIONE_TOTALE = 200 * 1024 * 1024


class ErroreImportazione(Exception):
    pass


@dataclass
class Esito:
    file: str
    stato: str  # importata, presente, errore
    messaggio: str = ""
    fattura: Fattura | None = None
    avvisi: list = field(default_factory=list)


@dataclass
class Resoconto:
    esiti: list = field(default_factory=list)
    clienti_creati: list = field(default_factory=list)
    azienda_creata: bool = False
    testo_piede_impostato: bool = False
    incassi_creati: int = 0
    avvisi_csv: list = field(default_factory=list)
    file_ignorati: int = 0

    @property
    def importate(self):
        return [e for e in self.esiti if e.stato == "importata"]

    @property
    def errori(self):
        return [e for e in self.esiti if e.stato == "errore"]


# --- Lettura dei file -----------------------------------------------------------------


def file_xml_da_zip(contenuto: bytes):
    """Restituisce (nome, xml) per ogni fattura nello ZIP. I PDF e gli altri file vengono ignorati."""
    try:
        archivio = zipfile.ZipFile(io.BytesIO(contenuto))
    except zipfile.BadZipFile as errore:
        raise ErroreImportazione("Il file caricato non è uno ZIP valido.") from errore
    voci = archivio.infolist()
    if len(voci) > MAX_FILE_NELLO_ZIP:
        raise ErroreImportazione("Lo ZIP contiene troppi file.")
    if sum(v.file_size for v in voci) > MAX_DIMENSIONE_TOTALE:
        raise ErroreImportazione("Lo ZIP decompresso è troppo grande.")
    risultato, ignorati = [], 0
    for voce in voci:
        nome = voce.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if voce.is_dir() or not nome.lower().endswith((".xml", ".xml.p7m")) or nome.startswith("."):
            ignorati += 0 if voce.is_dir() else 1
            continue
        if voce.file_size > MAX_DIMENSIONE_FILE:
            raise ErroreImportazione(f"Il file {nome} è troppo grande.")
        risultato.append((nome, archivio.read(voce)))
    return risultato, ignorati


def _testo(el, percorso):
    trovato = el.find(percorso) if el is not None else None
    return trovato.text.strip() if trovato is not None and trovato.text else ""


def _decimale(testo, predefinito=None):
    try:
        return Decimal(testo) if testo else predefinito
    except InvalidOperation:
        return predefinito


def _data(testo):
    try:
        return datetime.strptime(testo, "%Y-%m-%d").date() if testo else None
    except ValueError:
        return None


def _anagrafica(el):
    """Campi comuni di CedentePrestatore e CessionarioCommittente."""
    dati = el.find("{*}DatiAnagrafici")
    sede = el.find("{*}Sede")
    id_iva = dati.find("{*}IdFiscaleIVA") if dati is not None else None
    return {
        "id_paese": _testo(id_iva, "{*}IdPaese"),
        "partita_iva": _testo(id_iva, "{*}IdCodice"),
        "codice_fiscale": _testo(dati, "{*}CodiceFiscale").upper(),
        "denominazione": _testo(dati, "{*}Anagrafica/{*}Denominazione")[:80],
        "nome": _testo(dati, "{*}Anagrafica/{*}Nome")[:60],
        "cognome": _testo(dati, "{*}Anagrafica/{*}Cognome")[:60],
        "regime_fiscale": _testo(dati, "{*}RegimeFiscale"),
        "indirizzo": _testo(sede, "{*}Indirizzo")[:60],
        "numero_civico": _testo(sede, "{*}NumeroCivico")[:8],
        "cap": _testo(sede, "{*}CAP")[:5],
        "comune": _testo(sede, "{*}Comune")[:60],
        "provincia": _testo(sede, "{*}Provincia")[:2].upper(),
        "nazione": (_testo(sede, "{*}Nazione") or "IT")[:2].upper(),
    }


def _riga_di_servizio(linea):
    """Righe che Flextax aggiunge in automatico e che qui sono gestite altrove.

    - "Imposta di bollo assolta in modo virtuale": nel programma è la casella "bollo a carico
      del cliente" (prezzo 2 € = addebitato, 0 € = a tuo carico);
    - riga "NOTA" a prezzo zero: il testo dei riferimenti normativi, che qui
      è il "testo a piè di fattura" dei dati azienda.
    Restituisce "bollo", "nota" oppure None.
    """
    descrizione = _testo(linea, "{*}Descrizione").lower()
    if descrizione.startswith("imposta di bollo"):
        return "bollo"
    # Flextax la marca con CodiceArticolo (CodiceTipo NOTA) oppure con AltriDatiGestionali (TipoDato NOTA).
    tipi = [_testo(a, "{*}TipoDato").upper() for a in linea.findall("{*}AltriDatiGestionali")]
    tipi += [_testo(c, "{*}CodiceTipo").upper() for c in linea.findall("{*}CodiceArticolo")]
    if "NOTA" in tipi and not _decimale(_testo(linea, "{*}PrezzoTotale"), Decimal("0")):
        return "nota"
    return None


@dataclass
class FatturaLetta:
    nome_file: str
    progressivo: str
    xml: str
    cedente: dict
    cliente: dict
    codice_destinatario: str
    pec_destinatario: str
    tipo_documento: str
    numero: int
    data: date
    causale: str
    righe: list
    bollo_addebitato: bool
    totale_dichiarato: Decimal | None
    condizioni_pagamento: str
    modalita_pagamento: str
    scadenze: list  # [(data, importo)]
    iban: str
    istituto_finanziario: str
    nota: str


def leggi_fattura_flextax(nome_file: str, contenuto: bytes) -> FatturaLetta:
    m = RE_NOME.match(nome_file)
    if not m:
        raise ErroreImportazione("nome file non riconosciuto (atteso IT<codice fiscale>_<progressivo>.xml)")
    if nome_file.lower().endswith(".p7m"):
        try:
            contenuto = estrai_da_p7m(contenuto)
        except Exception as errore:  # noqa: BLE001 - qualsiasi errore di decodifica
            raise ErroreImportazione("firma .p7m non leggibile") from errore
    try:
        radice = etree.fromstring(contenuto, parser_sicuro())
    except etree.XMLSyntaxError as errore:
        raise ErroreImportazione(f"XML non valido: {errore}") from errore
    if etree.QName(radice).localname != "FatturaElettronica":
        raise ErroreImportazione("non è una fattura elettronica")
    corpi = radice.findall("{*}FatturaElettronicaBody")
    if len(corpi) != 1:
        raise ErroreImportazione("i lotti di più fatture in un solo file non sono gestiti")
    corpo = corpi[0]
    testata = radice.find("{*}FatturaElettronicaHeader")
    generali = corpo.find("{*}DatiGenerali/{*}DatiGeneraliDocumento")
    numero_testo = _testo(generali, "{*}Numero")
    if not numero_testo.isdigit():
        # Il programma numera le fatture con un intero per anno (es. "16"; "16/2026" non è gestito).
        raise ErroreImportazione(f"numero \"{numero_testo}\" non numerico")
    data_documento = _data(_testo(generali, "{*}Data"))
    if data_documento is None:
        raise ErroreImportazione("data del documento mancante")

    righe, bollo_addebitato, nota = [], False, ""
    for linea in corpo.findall("{*}DatiBeniServizi/{*}DettaglioLinee"):
        servizio = _riga_di_servizio(linea)
        if servizio == "bollo":
            bollo_addebitato = bollo_addebitato or bool(_decimale(_testo(linea, "{*}PrezzoTotale"), Decimal("0")))
            continue
        if servizio == "nota":
            nota = nota or _testo(linea, "{*}Descrizione")
            continue
        righe.append({
            "descrizione": _testo(linea, "{*}Descrizione")[:1000],
            "quantita": _decimale(_testo(linea, "{*}Quantita"), Decimal("1")),
            "unita_misura": _testo(linea, "{*}UnitaMisura")[:10],
            "prezzo_unitario": _decimale(_testo(linea, "{*}PrezzoUnitario"), Decimal("0")),
            "aliquota_iva": _decimale(_testo(linea, "{*}AliquotaIVA"), Decimal("0")),
            "natura": _testo(linea, "{*}Natura"),
        })
    if not righe:
        raise ErroreImportazione("nessuna riga di dettaglio")

    pagamento = corpo.find("{*}DatiPagamento")
    dettagli = pagamento.findall("{*}DettaglioPagamento") if pagamento is not None else []
    scadenze = [
        (_data(_testo(d, "{*}DataScadenzaPagamento")), _decimale(_testo(d, "{*}ImportoPagamento")))
        for d in dettagli
    ]
    primo = dettagli[0] if dettagli else None
    terzo = testata.find("{*}DatiTrasmissione")
    return FatturaLetta(
        nome_file=nome_file,
        progressivo=m.group("prog").upper().rjust(5, "0"),
        xml=contenuto.decode("utf-8", errors="replace"),
        cedente=_anagrafica(testata.find("{*}CedentePrestatore")),
        cliente=_anagrafica(testata.find("{*}CessionarioCommittente")),
        codice_destinatario=_testo(terzo, "{*}CodiceDestinatario").upper(),
        pec_destinatario=_testo(terzo, "{*}PECDestinatario"),
        tipo_documento=_testo(generali, "{*}TipoDocumento"),
        numero=int(numero_testo),
        data=data_documento,
        causale=" ".join(c.text.strip() for c in generali.findall("{*}Causale") if c.text),
        righe=righe,
        bollo_addebitato=bollo_addebitato,
        totale_dichiarato=_decimale(_testo(generali, "{*}ImportoTotaleDocumento")),
        condizioni_pagamento=_testo(pagamento, "{*}CondizioniPagamento"),
        modalita_pagamento=_testo(primo, "{*}ModalitaPagamento"),
        scadenze=scadenze,
        iban=_testo(primo, "{*}IBAN").replace(" ", "")[:34],
        istituto_finanziario=_testo(primo, "{*}IstitutoFinanziario")[:80],
        nota=nota,
    )


# --- Scrittura nel database -------------------------------------------------------------


def _azienda(letta: FatturaLetta, novita: dict) -> Azienda:
    azienda = Azienda.objects.first()
    ced = letta.cedente
    if azienda is None:
        campi = {k: ced[k] for k in ("denominazione", "nome", "cognome", "indirizzo", "numero_civico", "cap", "comune", "provincia", "nazione")}
        regime = ced["regime_fiscale"] if ced["regime_fiscale"] in RegimeFiscale.values else RegimeFiscale.FORFETTARIO
        azienda = Azienda.objects.create(
            partita_iva=ced["partita_iva"], codice_fiscale=ced["codice_fiscale"] or ced["partita_iva"],
            regime_fiscale=regime, iban=letta.iban, istituto_finanziario=letta.istituto_finanziario, **campi,
        )
        novita["azienda_creata"] = True
    elif ced["partita_iva"] and ced["partita_iva"] != azienda.partita_iva:
        raise ErroreImportazione(
            f"la fattura è stata emessa dalla partita IVA {ced['partita_iva']}, diversa da quella nei dati azienda"
        )
    if letta.nota and not azienda.testo_piede:
        azienda.testo_piede = letta.nota
        azienda.save(update_fields=["testo_piede"])
        novita["testo_piede_impostato"] = True
    return azienda


def _cliente(letta: FatturaLetta, novita: dict) -> Cliente:
    dati = letta.cliente
    estero = dati["nazione"] != "IT"
    partita_iva = (dati["id_paese"] + dati["partita_iva"]) if estero and dati["partita_iva"] else dati["partita_iva"]
    cliente = None
    if partita_iva:
        cliente = Cliente.objects.filter(partita_iva__iexact=partita_iva).first()
    if cliente is None and dati["codice_fiscale"]:
        cliente = Cliente.objects.filter(codice_fiscale__iexact=dati["codice_fiscale"], partita_iva="").first()
        if cliente is None and not partita_iva:
            cliente = Cliente.objects.filter(codice_fiscale__iexact=dati["codice_fiscale"]).first()
    if cliente is not None:
        return cliente
    codice = letta.codice_destinatario if len(letta.codice_destinatario) == 7 else "0000000"
    cliente = Cliente.objects.create(
        denominazione=dati["denominazione"], nome=dati["nome"], cognome=dati["cognome"],
        partita_iva=partita_iva, codice_fiscale=dati["codice_fiscale"],
        indirizzo=dati["indirizzo"], numero_civico=dati["numero_civico"], cap=dati["cap"],
        comune=dati["comune"], provincia=dati["provincia"], nazione=dati["nazione"],
        codice_destinatario="XXXXXXX" if estero else codice,
        pec=letta.pec_destinatario[:254] if codice == "0000000" else "",
        note="Importato da Flextax.",
    )
    novita["cliente_creato"] = cliente
    return cliente


def _crea_fattura(letta: FatturaLetta, cliente: Cliente, esito: Esito) -> Fattura:
    if letta.tipo_documento not in TipoDocumento.values:
        raise ErroreImportazione(f"tipo documento {letta.tipo_documento} non gestito dal programma")
    for riga in letta.righe:
        if riga["natura"] and riga["natura"] not in Natura.values:
            raise ErroreImportazione(f"natura {riga['natura']} non gestita dal programma")
    a_rate = letta.condizioni_pagamento == CondizioniPagamento.RATE and len(letta.scadenze) > 1
    prima_scadenza = next((d for d, _ in letta.scadenze if d), None)
    modalita = letta.modalita_pagamento if letta.modalita_pagamento in ModalitaPagamento.values else ModalitaPagamento.BONIFICO
    fattura = Fattura.objects.create(
        cliente=cliente, tipo_documento=letta.tipo_documento, numero=letta.numero, data=letta.data,
        causale=letta.causale,
        condizioni_pagamento=CondizioniPagamento.RATE if a_rate else CondizioniPagamento.COMPLETO,
        modalita_pagamento=modalita,
        termini_pagamento=TerminiPagamento.LIBERA,
        data_scadenza=None if a_rate else prima_scadenza,
        numero_rate=len(letta.scadenze) if a_rate else None,
        bollo_a_carico_cliente=letta.bollo_addebitato,
        stato=Fattura.Stato.IMPORTATA,
        progressivo_invio=letta.progressivo,
        xml=letta.xml,
    )
    RigaFattura.objects.bulk_create(
        RigaFattura(fattura=fattura, ordine=i, **riga) for i, riga in enumerate(letta.righe)
    )
    if a_rate:
        Rata.objects.bulk_create(
            Rata(fattura=fattura, data_scadenza=d, importo=importo) for d, importo in letta.scadenze if d
        )
    # Controllo: il totale ricalcolato deve corrispondere a quello da pagare nel file.
    totale = calcola_totali(fattura.righe.all(), fattura.bollo_a_carico_cliente).totale_documento
    da_pagare = sum((i for _, i in letta.scadenze if i), Decimal("0"))
    riferimento = da_pagare or letta.totale_dichiarato
    if riferimento is not None and riferimento != totale:
        esito.avvisi.append(f"Totale ricalcolato {totale} €, nel file {riferimento} €.")
    if letta.totale_dichiarato is not None and da_pagare and letta.totale_dichiarato != da_pagare:
        esito.avvisi.append(
            f"Nel file il totale documento ({letta.totale_dichiarato} €) è diverso dall'importo da pagare ({da_pagare} €)."
        )
    return fattura


def _aggiorna_progressivo(progressivi):
    """Il prossimo file generato dal programma non deve riusare un nome già inviato allo SdI."""
    valori = [int(p, 36) for p in progressivi]
    if not valori:
        return
    contatore, _ = Contatore.objects.select_for_update().get_or_create(nome="progressivo_invio")
    if max(valori) > contatore.valore:
        contatore.valore = max(valori)
        contatore.save(update_fields=["valore"])


def importa_fatture(file_xml, resoconto: Resoconto | None = None) -> Resoconto:
    """Importa le fatture. Ogni file è indipendente: un errore non blocca gli altri."""
    resoconto = resoconto or Resoconto()
    progressivi = []
    for nome, contenuto in sorted(file_xml):
        esito = Esito(file=nome, stato="errore")
        resoconto.esiti.append(esito)
        try:
            letta = leggi_fattura_flextax(nome, contenuto)
            novita = {}
            with transaction.atomic():
                esistente = Fattura.objects.filter(anno=letta.data.year, numero=letta.numero).first()
                if esistente is not None:
                    esito.fattura = esistente
                    if esistente.stato == Fattura.Stato.IMPORTATA and esistente.progressivo_invio == letta.progressivo:
                        esito.stato, esito.messaggio = "presente", "già importata"
                        progressivi.append(letta.progressivo)
                    else:
                        esito.messaggio = f"esiste già la fattura {esistente.numero_documento} nel programma"
                    continue
                azienda = _azienda(letta, novita)
                if letta.cedente["codice_fiscale"] and letta.cedente["codice_fiscale"] != azienda.codice_fiscale.upper():
                    esito.avvisi.append("Il codice fiscale del cedente è diverso da quello nei dati azienda.")
                cliente = _cliente(letta, novita)
                esito.fattura = _crea_fattura(letta, cliente, esito)
                esito.stato = "importata"
                progressivi.append(letta.progressivo)
            # Solo dopo il commit: se la fattura fallisce, anche cliente e azienda vengono annullati.
            resoconto.azienda_creata |= novita.get("azienda_creata", False)
            resoconto.testo_piede_impostato |= novita.get("testo_piede_impostato", False)
            if "cliente_creato" in novita:
                resoconto.clienti_creati.append(novita["cliente_creato"])
        except ErroreImportazione as errore:
            esito.messaggio = str(errore)
    with transaction.atomic():
        _aggiorna_progressivo(progressivi)
    return resoconto


# --- CSV degli incassi -----------------------------------------------------------------------


def _importo_csv(testo):
    pulito = (testo or "").replace("€", "").replace(".", "").replace(",", ".").replace("\xa0", "").strip()
    return _decimale(pulito, Decimal("0"))


def _data_csv(testo):
    testo = (testo or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(testo, formato).date()
        except ValueError:
            continue
    return None


def _numero_csv(testo):
    # Flextax scrive il numero come formula Excel: ="16"
    cifre = re.sub(r'^="?|"$', "", (testo or "").strip())
    return int(cifre) if cifre.isdigit() else None


def leggi_csv(contenuto: bytes):
    """Restituisce una lista di dict: anno, numero, cliente, incassata, acconti [(data, importo)]."""
    try:
        testo = contenuto.decode("utf-8-sig")
    except UnicodeDecodeError:
        testo = contenuto.decode("cp1252")
    lettore = csv.DictReader(io.StringIO(testo), delimiter=";")
    obbligatorie = {"Numero", "Data", "Acconto 1", "Data acconto 1"}
    if not lettore.fieldnames or not obbligatorie <= set(lettore.fieldnames):
        raise ErroreImportazione("Il CSV non ha le colonne attese dell'export Flextax (Numero, Data, Acconto 1, ...).")
    documenti = []
    for riga in lettore:
        data_doc = _data_csv(riga.get("Data"))
        numero = _numero_csv(riga.get("Numero"))
        if data_doc is None or numero is None:
            continue
        acconti = []
        for i in range(1, 7):
            importo = _importo_csv(riga.get(f"Acconto {i}"))
            if importo > 0:
                acconti.append((_data_csv(riga.get(f"Data acconto {i}")), importo))
        documenti.append({
            "anno": data_doc.year, "numero": numero, "cliente": (riga.get("Cliente") or "").strip(),
            "incassata": (riga.get("Incassata") or "").strip().upper() == "SI", "acconti": acconti,
        })
    return documenti


def importa_incassi(contenuto: bytes, resoconto: Resoconto | None = None) -> Resoconto:
    resoconto = resoconto or Resoconto()
    for doc in leggi_csv(contenuto):
        rif = f"Fattura {doc['numero']}/{doc['anno']}"
        fattura = Fattura.objects.filter(anno=doc["anno"], numero=doc["numero"]).first()
        if fattura is None:
            if doc["acconti"]:
                resoconto.avvisi_csv.append(f"{rif}: non presente nel programma, incassi non importati.")
            continue
        for data_incasso, importo in doc["acconti"]:
            if data_incasso is None:
                resoconto.avvisi_csv.append(f"{rif}: incasso di {importo} € senza data, non importato.")
                continue
            _, creato = Incasso.objects.get_or_create(
                fattura=fattura, data=data_incasso, importo=importo, defaults={"note": "Importato da Flextax."}
            )
            resoconto.incassi_creati += int(creato)
    return resoconto
