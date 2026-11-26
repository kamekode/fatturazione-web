"""Calcolo di importi, riepiloghi IVA e bollo, indipendente dal formato XML."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTESIMO = Decimal("0.01")
SOGLIA_BOLLO = Decimal("77.47")
IMPORTO_BOLLO = Decimal("2.00")
# Righe senza IVA che concorrono alla soglia del bollo (2 euro oltre 77,47 euro).
# Il caso principale è il forfettario (N2.2). Da rivedere se si usano altre nature.
NATURE_SOGGETTE_A_BOLLO = {"N2.1", "N2.2", "N4"}


def arrotonda(valore: Decimal) -> Decimal:
    return valore.quantize(CENTESIMO, rounding=ROUND_HALF_UP)


def totale_riga(riga) -> Decimal:
    return arrotonda(riga.quantita * riga.prezzo_unitario)


@dataclass
class Riepilogo:
    aliquota_iva: Decimal
    natura: str
    imponibile: Decimal
    imposta: Decimal


@dataclass
class Totali:
    riepiloghi: list
    imponibile: Decimal
    imposta: Decimal
    totale_documento: Decimal
    bollo: Decimal

    @property
    def bollo_virtuale(self):
        return self.bollo > 0


def calcola_totali(righe) -> Totali:
    gruppi = {}
    for riga in righe:
        chiave = (riga.aliquota_iva.quantize(CENTESIMO), riga.natura or "")
        gruppi[chiave] = gruppi.get(chiave, Decimal("0")) + totale_riga(riga)
    riepiloghi = []
    for (aliquota, natura), imponibile in sorted(gruppi.items(), key=lambda g: (g[0][0], g[0][1])):
        imponibile = arrotonda(imponibile)
        imposta = arrotonda(imponibile * aliquota / 100)
        riepiloghi.append(Riepilogo(aliquota, natura, imponibile, imposta))
    imponibile = sum((r.imponibile for r in riepiloghi), Decimal("0.00"))
    imposta = sum((r.imposta for r in riepiloghi), Decimal("0.00"))
    esente = sum((r.imponibile for r in riepiloghi if r.natura in NATURE_SOGGETTE_A_BOLLO), Decimal("0"))
    bollo = IMPORTO_BOLLO if esente > SOGLIA_BOLLO else Decimal("0.00")
    return Totali(riepiloghi, imponibile, imposta, imponibile + imposta, bollo)


# --- Scadenze --------------------------------------------------------------------

def fine_mese(giorno):
    import calendar

    return giorno.replace(day=calendar.monthrange(giorno.year, giorno.month)[1])


def _parti_termini(termini):
    """Da un codice come "60FM" ricava giorni (60) e se va a fine mese (True)."""
    fm = termini.endswith("FM")
    numero = termini[:-2] if fm else termini
    giorni = int(numero) if numero.isdigit() else 0
    return giorni, fm


def calcola_scadenza(data, termini, multiplo=1):
    """Scadenza per i termini indicati. `multiplo` serve per le rate (30, 60, 90...)."""
    from datetime import timedelta

    if termini in ("", "LIBERA"):
        return None
    giorni, fm = _parti_termini(termini)
    scadenza = data + timedelta(days=giorni * multiplo)
    return fine_mese(scadenza) if fm else scadenza


def scadenze_rate(data, termini, numero_rate):
    """Una scadenza per rata, a intervalli regolari. Con termini senza giorni l'intervallo è 30 gg."""
    giorni, fm = _parti_termini(termini if termini != "LIBERA" else "30")
    passo = f"{giorni or 30}{'FM' if fm else ''}"
    return [calcola_scadenza(data, passo, i) for i in range(1, numero_rate + 1)]


class ErroreRate(ValueError):
    pass


def ripartisci_rate(totale, importi):
    """Completa gli importi delle rate: quelli vuoti (None) si dividono il resto in parti uguali.

    L'ultima rata vuota assorbe gli arrotondamenti. La somma deve coincidere col totale.
    """
    fissi = sum((i for i in importi if i is not None), Decimal("0"))
    vuoti = [n for n, i in enumerate(importi) if i is None]
    resto = totale - fissi
    risultato = list(importi)
    if vuoti:
        if resto <= 0:
            raise ErroreRate("Gli importi delle rate superano già il totale della fattura.")
        quota = arrotonda(resto / len(vuoti))
        for n in vuoti[:-1]:
            risultato[n] = quota
        risultato[vuoti[-1]] = resto - quota * (len(vuoti) - 1)
    if sum(risultato, Decimal("0")) != totale:
        raise ErroreRate(f"La somma delle rate ({sum(risultato, Decimal('0'))}) non coincide col totale ({totale}).")
    return risultato
