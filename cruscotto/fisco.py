"""Stima di imposte e contributi, con la spiegazione di ogni numero.

Ogni regime fiscale è una classe con lo stesso metodo `stima(anno)`, così il passaggio
all'ordinario richiederà solo una nuova classe (vedi RegimeOrdinario).

Fonti (Agenzia delle Entrate):
- scheda "Regime forfetario - Che cos'è": coefficiente di redditività, deduzione dei contributi,
  imposta sostitutiva 15% (5% per i primi cinque anni con i requisiti), soglie 85.000 e 100.000 euro;
- istruzioni Redditi PF, fascicolo 3, quadro LM: tabella dei coefficienti (allegato 2, L. 145/2018);
- istruzioni Redditi 2026 e risoluzione 93/E del 12/11/2019: acconto del 100% dell'imposta dell'anno
  precedente, non dovuto fino a 51,65 euro, in unica soluzione a novembre sotto 257,52 euro,
  altrimenti in due rate del 50% (soggetti ISA, compresi i forfetari) a giugno e novembre.
I contributi INPS sono una stima con i parametri inseriti nel profilo fiscale.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from anagrafiche.models import Azienda, RegimeFiscale

from .dati import ZERO, incassi_anno
from .models import ProfiloFiscale, Versamento

SOGLIA_ACCESSO = Decimal("85000")
SOGLIA_USCITA = Decimal("100000")
ACCONTO_MINIMO = Decimal("51.65")
ACCONTO_UNICA_RATA = Decimal("257.52")
RIDUZIONE_CONTRIBUTIVA = Decimal("0.35")
CENTO = Decimal("100")


def euro(valore):
    return Decimal(valore).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(valore):
    testo = f"{euro(valore):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{testo} €"


def _perc(valore):
    return f"{Decimal(valore).normalize():f}".replace(".", ",") + "%"


@dataclass
class Voce:
    nome: str
    importo: Decimal
    spiegazione: str
    evidenza: bool = False


@dataclass
class ScadenzaFiscale:
    data: date
    descrizione: str
    importo: Decimal


@dataclass
class Stima:
    anno: int
    regime: str
    voci: list = field(default_factory=list)
    scadenze: list = field(default_factory=list)
    avvisi: list = field(default_factory=list)
    da_accantonare: Decimal = ZERO
    percentuale_accantonamento: Decimal | None = None
    disponibile: bool = True


def _versato(anno_riferimento=None, tipi=(), nell_anno=None):
    versamenti = Versamento.objects.filter(tipo__in=tipi)
    if anno_riferimento is not None:
        versamenti = versamenti.filter(anno_riferimento=anno_riferimento)
    if nell_anno is not None:
        versamenti = versamenti.filter(data__year=nell_anno)
    return versamenti.aggregate(t=Sum("importo"))["t"] or ZERO


def giorno_feriale(giorno):
    """Le scadenze di sabato o domenica slittano al lunedì (istruzioni Redditi)."""
    while giorno.weekday() >= 5:
        giorno += timedelta(days=1)
    return giorno


def piano_acconti(imposta, anno):
    """Acconti dovuti per `anno` sulla base dell'imposta dell'anno precedente (metodo storico)."""
    imposta = euro(imposta)
    if imposta <= ACCONTO_MINIMO:
        return []
    if imposta < ACCONTO_UNICA_RATA:
        return [ScadenzaFiscale(giorno_feriale(date(anno, 11, 30)), f"Acconto unico imposta {anno}", imposta)]
    prima = euro(imposta / 2)
    return [
        ScadenzaFiscale(giorno_feriale(date(anno, 6, 30)), f"Primo acconto imposta {anno} (50%)", prima),
        ScadenzaFiscale(giorno_feriale(date(anno, 11, 30)), f"Secondo acconto imposta {anno} (50%)", imposta - prima),
    ]


class RegimeForfettario:
    nome = "Forfettario"

    def __init__(self, profilo: ProfiloFiscale):
        self.profilo = profilo

    def contributi_stimati(self, reddito):
        """Contributi INPS dovuti sul reddito dell'anno, secondo i parametri del profilo."""
        p = self.profilo
        aliquota = p.aliquota_contributi / CENTO
        if p.gestione_previdenziale == ProfiloFiscale.Gestione.SEPARATA:
            return euro(reddito * aliquota), (
                f"Gestione separata: {_perc(p.aliquota_contributi)} del reddito forfettario ({_fmt(reddito)})."
            )
        fissi = p.contributi_fissi
        eccedenza = max(reddito - p.reddito_minimale, ZERO) * aliquota
        totale = fissi + eccedenza
        testo = (
            f"Contributi fissi {_fmt(fissi)} più {_perc(p.aliquota_contributi)} sulla parte di reddito forfettario "
            f"oltre il minimale di {_fmt(p.reddito_minimale)} ({_fmt(eccedenza)})."
        )
        if p.riduzione_contributiva:
            totale = totale * (1 - RIDUZIONE_CONTRIBUTIVA)
            testo += " Con la riduzione del 35% per i forfettari."
        return euro(totale), testo

    def stima(self, anno, oggi=None):
        oggi = oggi or date.today()
        p = self.profilo
        stima = Stima(anno=anno, regime=self.nome)
        coeff = p.coefficiente_redditivita / CENTO
        aliquota = p.aliquota_imposta / CENTO

        incassi = list(incassi_anno(anno))
        ricavi = sum((-i.importo if i.fattura.tipo_documento == "TD04" else i.importo for i in incassi), ZERO)
        stima.voci.append(Voce(
            "Ricavi incassati", ricavi,
            f"Somma degli incassi registrati con data nel {anno} ({len(incassi)} pagamenti). Nel forfettario conta "
            "quando incassi, non quando emetti la fattura (criterio di cassa).",
        ))
        reddito = euro(ricavi * coeff)
        stima.voci.append(Voce(
            "Reddito forfettario", reddito,
            f"Ricavi × coefficiente di redditività {_perc(p.coefficiente_redditivita)}"
            f"{' (ATECO ' + p.codice_ateco + ')' if p.codice_ateco else ''}. Il resto è considerato spese, "
            "che nel forfettario non si deducono una per una.",
        ))
        contributi_versati = _versato(tipi=Versamento.CONTRIBUTI, nell_anno=anno)
        stima.voci.append(Voce(
            "Contributi versati nell'anno (deducibili)", contributi_versati,
            f"Contributi previdenziali obbligatori pagati nel {anno}, registrati nei versamenti. Si deducono "
            "dal reddito nell'anno in cui li paghi.",
        ))
        imponibile = max(reddito - contributi_versati, ZERO)
        stima.voci.append(Voce("Reddito imponibile", imponibile, "Reddito forfettario meno i contributi versati."))
        imposta = euro(imponibile * aliquota)
        stima.voci.append(Voce(
            "Imposta sostitutiva", imposta,
            f"{_perc(p.aliquota_imposta)} del reddito imponibile. Sostituisce IRPEF, addizionali e IRAP.",
            evidenza=True,
        ))
        acconti = _versato(anno_riferimento=anno, tipi=[Versamento.Tipo.IMPOSTA_ACCONTO])
        stima.voci.append(Voce(
            "Acconti d'imposta già versati", acconti,
            f"Acconti registrati con anno di riferimento {anno} (calcolati sull'imposta dell'anno prima).",
        ))
        saldo = imposta - acconti
        stima.voci.append(Voce(
            f"Saldo imposta (giugno {anno + 1})" if saldo >= 0 else "Credito d'imposta", saldo,
            f"Imposta {anno} meno acconti versati. Si paga entro il 30 giugno {anno + 1} insieme al primo acconto "
            f"{anno + 1}." if saldo >= 0 else "Gli acconti superano l'imposta stimata: la differenza è un credito.",
            evidenza=True,
        ))
        if saldo > 0:
            stima.scadenze.append(ScadenzaFiscale(giorno_feriale(date(anno + 1, 6, 30)), f"Saldo imposta sostitutiva {anno}", saldo))
        stima.scadenze += piano_acconti(imposta, anno + 1)

        if p.contributi_configurati:
            contributi, testo = self.contributi_stimati(reddito)
            stima.voci.append(Voce(f"Contributi INPS {anno} stimati", contributi, testo, evidenza=True))
            gia_pagati = _versato(anno_riferimento=anno, tipi=Versamento.CONTRIBUTI)
            stima.voci.append(Voce(
                f"Contributi {anno} già versati", gia_pagati, f"Versamenti di contributi con anno di riferimento {anno}.",
            ))
            residuo_contributi = max(contributi - gia_pagati, ZERO)
        else:
            residuo_contributi = ZERO
            if p.gestione_previdenziale != ProfiloFiscale.Gestione.NESSUNA:
                stima.avvisi.append(
                    "Contributi non stimati: inserisci minimale, contributi fissi e aliquota INPS nel profilo fiscale."
                )

        stima.da_accantonare = max(saldo, ZERO) + residuo_contributi
        quota_contributi = (p.aliquota_contributi / CENTO) if p.contributi_configurati else ZERO
        if p.riduzione_contributiva:
            quota_contributi *= 1 - RIDUZIONE_CONTRIBUTIVA
        stima.percentuale_accantonamento = (coeff * (aliquota + quota_contributi) * CENTO).quantize(Decimal("0.1"))

        if ricavi > SOGLIA_USCITA:
            stima.avvisi.append(
                f"Ricavi oltre {_fmt(SOGLIA_USCITA)}: il forfettario cessa già da quest'anno e l'IVA è dovuta "
                "dall'operazione che ha superato la soglia."
            )
        elif ricavi > SOGLIA_ACCESSO:
            stima.avvisi.append(
                f"Ricavi oltre {_fmt(SOGLIA_ACCESSO)}: dall'anno prossimo non potrai restare nel forfettario."
            )
        if p.anno_inizio_attivita and p.aliquota_imposta == 5 and anno > p.anno_inizio_attivita + 4:
            stima.avvisi.append("L'aliquota del 5% vale per i primi cinque anni di attività: controlla il profilo fiscale.")
        if anno == oggi.year:
            stima.avvisi.append("Anno in corso: la stima usa solo gli incassi registrati fin qui.")
        return stima


class RegimeOrdinario:
    """Da completare quando servirà: IRPEF a scaglioni, IVA, costi deducibili."""

    nome = "Ordinario"

    def __init__(self, profilo):
        self.profilo = profilo

    def stima(self, anno, oggi=None):
        return Stima(anno=anno, regime=self.nome, disponibile=False, avvisi=[
            "La stima per il regime ordinario non è ancora disponibile."
        ])


def regime_corrente():
    azienda = Azienda.objects.first()
    profilo = ProfiloFiscale.corrente()
    if azienda is None or azienda.regime_fiscale == RegimeFiscale.FORFETTARIO:
        return RegimeForfettario(profilo)
    return RegimeOrdinario(profilo)
