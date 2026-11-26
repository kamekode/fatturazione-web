from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from fatture.models import Fattura, Incasso

from .dati import ZERO, posizioni, riepilogo_mensile
from .fisco import regime_corrente
from .forms import IncassoForm, ProfiloFiscaleForm, VersamentoForm
from .models import ProfiloFiscale, Versamento

ALTEZZA_GRAFICO = 160
NOMI_MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _anno(request):
    try:
        return int(request.GET.get("anno") or timezone.localdate().year)
    except ValueError:
        return timezone.localdate().year


def _grafico(mesi):
    """Barre in SVG calcolate dal server (la pagina non usa script né stili inline)."""
    massimo = max([max(m["fatturato"], m["incassato"]) for m in mesi] + [Decimal("1")])
    barre = []
    for i, m in enumerate(mesi):
        x = 10 + i * 50
        h_f = int(max(m["fatturato"], ZERO) / massimo * ALTEZZA_GRAFICO)
        h_i = int(max(m["incassato"], ZERO) / massimo * ALTEZZA_GRAFICO)
        barre.append({
            "nome": NOMI_MESI[i], "x_testo": x + 18,
            "x_f": x, "y_f": ALTEZZA_GRAFICO - h_f + 10, "h_f": h_f, "fatturato": m["fatturato"],
            "x_i": x + 18, "y_i": ALTEZZA_GRAFICO - h_i + 10, "h_i": h_i, "incassato": m["incassato"],
        })
    return {"barre": barre, "massimo": massimo, "y_testo": ALTEZZA_GRAFICO + 26}


def cruscotto(request):
    oggi = timezone.localdate()
    anno = _anno(request)
    tutte = posizioni()
    dell_anno = [p for p in tutte if p.fattura.anno == anno]
    mesi = riepilogo_mensile(anno)
    per_cliente = defaultdict(lambda: ZERO)
    for p in dell_anno:
        per_cliente[p.fattura.cliente] += p.segno * p.totale
    aperte = [p for p in tutte if p.aperta]
    contesto = {
        "anno": anno,
        "anni": sorted({oggi.year, *Fattura.objects.values_list("anno", flat=True).distinct()}, reverse=True),
        "fatturato": sum((p.segno * p.totale for p in dell_anno), ZERO),
        "numero_fatture": sum(1 for p in dell_anno if not p.nota_credito),
        "incassato": sum((m["incassato"] for m in mesi), ZERO),
        "da_incassare": sum((p.residuo for p in aperte), ZERO),
        "scaduto": sum((p.residuo for p in aperte if p.scaduta(oggi)), ZERO),
        "grafico": _grafico(mesi),
        "mesi": [dict(m, nome=NOMI_MESI[m["mese"] - 1]) for m in mesi],
        "clienti": sorted(per_cliente.items(), key=lambda c: -c[1])[:8],
        "stima": regime_corrente().stima(anno, oggi),
        "profilo": ProfiloFiscale.objects.first(),
    }
    return render(request, "cruscotto/cruscotto.html", contesto)


def scadenziario(request):
    oggi = timezone.localdate()
    aperte = sorted(
        (p for p in posizioni() if p.aperta),
        key=lambda p: (p.prossima_scadenza.data or date.max) if p.prossima_scadenza else date.max,
    )
    if request.GET.get("filtro") == "scadute":
        aperte = [p for p in aperte if p.scaduta(oggi)]
    regime = regime_corrente()
    fiscali = []
    for anno in (oggi.year - 1, oggi.year):
        fiscali += [s for s in regime.stima(anno, oggi).scadenze if s.data >= oggi]
    contesto = {
        "aperte": aperte, "oggi": oggi, "filtro": request.GET.get("filtro", ""),
        "totale": sum((p.residuo for p in aperte), ZERO),
        "fiscali": sorted(fiscali, key=lambda s: s.data),
    }
    return render(request, "cruscotto/scadenziario.html", contesto)


def incasso_nuovo(request, fattura_pk):
    fattura = get_object_or_404(Fattura, pk=fattura_pk)
    posizione = next((p for p in posizioni(fattura.anno) if p.fattura.pk == fattura.pk), None)
    if posizione is None:
        messages.error(request, "Gli incassi si registrano solo sulle fatture emesse.")
        return redirect("fattura_dettaglio", pk=fattura.pk)
    iniziali = {"data": timezone.localdate(), "importo": posizione.residuo or None}
    form = IncassoForm(request.POST or None, initial=iniziali)
    if request.method == "POST" and form.is_valid():
        incasso = form.save(commit=False)
        incasso.fattura = fattura
        incasso.save()
        if incasso.importo > posizione.residuo:
            messages.warning(request, "L'incasso supera il residuo da pagare: controlla l'importo.")
        messages.success(request, f"Incasso di {incasso.importo} € registrato.")
        if request.POST.get("torna") == "scadenziario":
            return redirect("scadenziario")
        return redirect("fattura_dettaglio", pk=fattura.pk)
    return render(request, "cruscotto/incasso_form.html", {"form": form, "fattura": fattura, "posizione": posizione,
                                                           "torna": request.GET.get("torna", "")})


def incasso_elimina(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    incasso = get_object_or_404(Incasso, pk=pk)
    fattura_pk = incasso.fattura_id
    incasso.delete()
    messages.success(request, "Incasso eliminato.")
    return redirect("fattura_dettaglio", pk=fattura_pk)


def profilo(request):
    form = ProfiloFiscaleForm(request.POST or None, instance=ProfiloFiscale.objects.first())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo fiscale salvato.")
        return redirect("cruscotto")
    return render(request, "cruscotto/profilo.html", {"form": form})


def versamenti(request):
    form = VersamentoForm(request.POST or None, initial={"anno_riferimento": timezone.localdate().year})
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Versamento registrato.")
        return redirect("versamenti")
    return render(request, "cruscotto/versamenti.html", {"form": form, "versamenti": Versamento.objects.all()})


def versamento_elimina(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    get_object_or_404(Versamento, pk=pk).delete()
    messages.success(request, "Versamento eliminato.")
    return redirect("versamenti")
