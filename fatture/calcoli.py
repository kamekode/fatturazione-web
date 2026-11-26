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
