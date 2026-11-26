"""DDT in PDF (A4) con ReportLab, senza prezzi e con gli spazi per le firme."""

import io

from django.utils.formats import date_format
from django.utils.timezone import localtime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


def _p(testo, stile):
    return Paragraph(escape(str(testo or "")).replace("\n", "<br/>"), stile)


def _soggetto(titolo, s, stili):
    righe = [f"<font size=8 color='#555555'>{titolo}</font>", f"<b>{escape(s.ragione_sociale)}</b>"]
    righe.append(escape(f"{s.indirizzo} {s.numero_civico}".strip()))
    righe.append(escape(f"{s.cap} {s.comune}" + (f" ({s.provincia})" if s.provincia else "")))
    fiscali = []
    if s.partita_iva:
        fiscali.append(f"P.IVA {s.partita_iva}")
    if s.codice_fiscale:
        fiscali.append(f"C.F. {s.codice_fiscale}")
    righe.append(escape(" · ".join(fiscali)))
    return Paragraph("<br/>".join(righe), stili["BodyText"])


def _quantita(q):
    testo = f"{q.normalize():f}"
    return testo.replace(".", ",")


def ddt_pdf(ddt, azienda) -> bytes:
    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"DDT {ddt.numero_documento}", author=azienda.ragione_sociale if azienda else "",
    )
    stili = getSampleStyleSheet()
    normale, piccolo = stili["BodyText"], stili["BodyText"].clone("piccolo", fontSize=8, textColor=colors.HexColor("#555555"))
    larghezza = documento.width
    griglia = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ])

    contenuto = [
        Paragraph(f"Documento di trasporto n. {ddt.numero_documento} del {ddt.data:%d/%m/%Y}", stili["Heading2"]),
        Paragraph("D.P.R. 472/1996", piccolo),
        Spacer(0, 4 * mm),
    ]
    soggetti = Table(
        [[_soggetto("Mittente", azienda, stili) if azienda else "", _soggetto("Destinatario", ddt.cliente, stili)]],
        colWidths=[larghezza / 2] * 2,
    )
    soggetti.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.5, colors.black), ("BOX", (1, 0), (1, 0), 0.5, colors.black),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    contenuto += [soggetti, Spacer(0, 3 * mm)]

    destinazione = ddt.destinazione or "Sede del destinatario"
    trasporto = ddt.get_trasporto_a_cura_display() + (f": {ddt.vettore}" if ddt.vettore else "")
    inizio = date_format(localtime(ddt.inizio_trasporto), "d/m/Y H:i") if ddt.inizio_trasporto else ""
    dati = Table(
        [["Luogo di destinazione", "Causale del trasporto", "Trasporto a cura del", "Inizio trasporto"],
         [_p(destinazione, normale), _p(ddt.causale_trasporto, normale), _p(trasporto, normale), inizio]],
        colWidths=[larghezza * 0.34, larghezza * 0.22, larghezza * 0.26, larghezza * 0.18],
    )
    dati.setStyle(griglia)
    contenuto += [dati, Spacer(0, 3 * mm)]

    righe = [["Codice", "Descrizione dei beni", "U.m.", "Quantità"]]
    for r in ddt.righe.select_related("articolo"):
        righe.append([_p(r.articolo.codice if r.articolo else "", normale), _p(r.descrizione, normale), r.unita_misura, _quantita(r.quantita)])
    beni = Table(righe, colWidths=[larghezza * 0.16, larghezza * 0.6, larghezza * 0.1, larghezza * 0.14], repeatRows=1)
    beni.setStyle(TableStyle(griglia.getCommands() + [("ALIGN", (3, 0), (3, -1), "RIGHT")]))
    contenuto += [beni, Spacer(0, 3 * mm)]

    aspetto = Table(
        [["Aspetto esteriore dei beni", "N. colli", "Peso (kg)"],
         [_p(ddt.aspetto_beni, normale), ddt.numero_colli or "", f"{ddt.peso_kg}".replace(".", ",") if ddt.peso_kg else ""]],
        colWidths=[larghezza * 0.6, larghezza * 0.2, larghezza * 0.2],
    )
    aspetto.setStyle(griglia)
    contenuto += [aspetto, Spacer(0, 3 * mm)]
    if ddt.note:
        note = Table([["Note"], [_p(ddt.note, normale)]], colWidths=[larghezza])
        note.setStyle(griglia)
        contenuto += [note]

    firme = Table([["", "", ""], ["Firma del mittente", "Firma del vettore", "Firma del destinatario"]],
                  colWidths=[larghezza / 3] * 3, rowHeights=[18 * mm, None])
    firme.setStyle(TableStyle([("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.black), ("FONTSIZE", (0, 1), (-1, 1), 8),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    contenuto += [Spacer(0, 8 * mm), firme]

    documento.build(contenuto)
    return buffer.getvalue()
