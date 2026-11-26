"""Dati di fatturato, incassi e scadenze ricavati dalle fatture."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch

from fatture.calcoli import ErroreRate, calcola_totali, ripartisci_rate
from fatture.codici import TipoDocumento
from fatture.models import Fattura, Incasso

ZERO = Decimal("0")

# Documenti fiscalmente emessi (o pronti per l'invio): esclusi bozze e scarti.
STATI_VALIDI = [
    Fattura.Stato.EMESSA, Fattura.Stato.INVIATA, Fattura.Stato.CONSEGNATA,
    Fattura.Stato.NON_RECAPITATA, Fattura.Stato.IMPORTATA,
]


@dataclass
class Scadenza:
    data: date | None
    importo: Decimal
    residuo: Decimal = ZERO


@dataclass
class Posizione:
    """Una fattura vista dallo scadenziario."""

    fattura: Fattura
    totale: Decimal
    incassato: Decimal
    scadenze: list = field(default_factory=list)

    @property
    def nota_credito(self):
        return self.fattura.tipo_documento == TipoDocumento.NOTA_CREDITO

    @property
    def segno(self):
        return -1 if self.nota_credito else 1

    @property
    def residuo(self):
        return max(self.totale - self.incassato, ZERO)

    @property
    def aperta(self):
        return not self.nota_credito and self.residuo > 0

    @property
    def prossima_scadenza(self):
        aperte = [s for s in self.scadenze if s.residuo > 0]
        return aperte[0] if aperte else None

    def scaduta(self, oggi):
        s = self.prossima_scadenza
        return bool(s and s.data and s.data < oggi)


def _scadenze(fattura, totale, incassato):
    rate = list(fattura.rate.all())
    if rate:
        try:
            importi = ripartisci_rate(totale, [r.importo for r in rate])
        except ErroreRate:
            importi = [r.importo or ZERO for r in rate]
        scadenze = [Scadenza(r.data_scadenza, i) for r, i in zip(rate, importi)]
    else:
        scadenze = [Scadenza(fattura.data_scadenza or fattura.data, totale)]
    # Gli incassi coprono le scadenze in ordine di data.
    resto = incassato
    for s in scadenze:
        coperto = min(s.importo, resto)
        s.residuo = s.importo - coperto
        resto -= coperto
    return scadenze


def posizioni(anno=None):
    fatture = (
        Fattura.objects.filter(stato__in=STATI_VALIDI)
        .select_related("cliente")
        .prefetch_related("righe", "rate", Prefetch("incassi", queryset=Incasso.objects.order_by("data")))
        .order_by("data", "numero")
    )
    if anno:
        fatture = fatture.filter(anno=anno)
    risultato = []
    for f in fatture:
        totale = calcola_totali(f.righe.all(), f.bollo_a_carico_cliente).totale_documento
        incassato = sum((i.importo for i in f.incassi.all()), ZERO)
        risultato.append(Posizione(f, totale, incassato, _scadenze(f, totale, incassato)))
    return risultato


def incassi_anno(anno):
    """Incassi registrati nell'anno (criterio di cassa), indipendentemente dalla data della fattura."""
    return Incasso.objects.filter(data__year=anno, fattura__stato__in=STATI_VALIDI).select_related("fattura", "fattura__cliente")


def riepilogo_mensile(anno):
    """Per ogni mese: fatturato (per data fattura) e incassato (per data incasso)."""
    mesi = [{"mese": m, "fatturato": ZERO, "incassato": ZERO} for m in range(1, 13)]
    for p in posizioni(anno):
        mesi[p.fattura.data.month - 1]["fatturato"] += p.segno * p.totale
    for i in incassi_anno(anno):
        segno = -1 if i.fattura.tipo_documento == TipoDocumento.NOTA_CREDITO else 1
        mesi[i.data.month - 1]["incassato"] += segno * i.importo
    return mesi
