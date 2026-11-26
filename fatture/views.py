from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from anagrafiche.models import Azienda
from catalogo.models import Articolo

from .calcoli import ErroreRate, calcola_totali, ripartisci_rate, scadenze_rate
from .codici import CondizioniPagamento
from .forms import FatturaForm, RateFormSet, RigheFormSet
from .models import Rata
from .models import Fattura
from .servizi import emetti
from .xml import ErroreFattura, anteprima_html, genera_xml, nome_file, versione_schema


def elenco(request):
    fatture = Fattura.objects.select_related("cliente").prefetch_related("righe")
    righe = [(f, calcola_totali(f.righe.all())) for f in fatture]
    return render(request, "fatture/elenco.html", {"righe": righe})


def modifica(request, pk=None):
    fattura = get_object_or_404(Fattura, pk=pk) if pk else Fattura()
    if pk and not fattura.modificabile:
        messages.error(request, "Una fattura emessa non si può modificare.")
        return redirect("fattura_dettaglio", pk=pk)
    if not Azienda.objects.exists():
        messages.warning(request, "Prima di creare fatture compila i dati della tua azienda.")
        return redirect("azienda")
    form = FatturaForm(request.POST or None, instance=fattura)
    formset = RigheFormSet(request.POST or None, instance=fattura)
    rate_formset = RateFormSet(request.POST or None, instance=fattura, prefix="rate")
    if request.method == "POST" and form.is_valid() and formset.is_valid() and rate_formset.is_valid():
        a_rate = form.cleaned_data["condizioni_pagamento"] == CondizioniPagamento.RATE
        rate_inserite = [
            f for f in rate_formset.forms
            if (f.instance.pk or f.has_changed()) and not f.cleaned_data.get("DELETE")
        ]
        if a_rate and len(rate_inserite) == 1:
            form.add_error("numero_rate", "Servono almeno 2 rate.")
        elif a_rate and not rate_inserite and not form.cleaned_data.get("numero_rate"):
            form.add_error("numero_rate", "Indica il numero di rate oppure inserisci le scadenze.")
        else:
            with transaction.atomic():
                fattura = form.save()
                formset.instance = fattura
                righe = formset.save(commit=False)
                for oggetto in formset.deleted_objects:
                    oggetto.delete()
                for ordine, riga in enumerate(righe):
                    riga.ordine = ordine
                    riga.save()
                _salva_rate(fattura, rate_formset, a_rate, bool(rate_inserite))
            messages.success(request, f"Fattura {fattura.numero_documento} salvata come bozza.")
            return redirect("fattura_dettaglio", pk=fattura.pk)
    # Dati degli articoli per compilare la riga appena si sceglie un articolo.
    articoli = {
        str(a.pk): {
            "descrizione": a.descrizione, "prezzo": f"{a.prezzo.normalize():f}", "unita_misura": a.unita_misura,
            "aliquota_iva": f"{a.aliquota_iva.normalize():f}", "natura": a.natura,
        }
        for a in Articolo.objects.filter(attivo=True)
    }
    contesto = {
        "form": form, "formset": formset, "rate_formset": rate_formset, "fattura": fattura if pk else None,
        "articoli": articoli,
    }
    return render(request, "fatture/form.html", contesto)


def _salva_rate(fattura, rate_formset, a_rate, rate_inserite):
    if not a_rate:
        fattura.rate.all().delete()
        return
    rate_formset.instance = fattura
    rate_formset.save()
    if not rate_inserite:
        # Nessuna scadenza inserita a mano: le generiamo dai termini di pagamento.
        for scadenza in scadenze_rate(fattura.data, fattura.termini_pagamento, fattura.numero_rate):
            Rata.objects.create(fattura=fattura, data_scadenza=scadenza)
    fattura.numero_rate = fattura.rate.count()
    fattura.save(update_fields=["numero_rate"])


def dettaglio(request, pk):
    fattura = get_object_or_404(Fattura.objects.select_related("cliente"), pk=pk)
    righe = list(fattura.righe.all())
    totali = calcola_totali(righe)
    rate, errore_rate = list(fattura.rate.all()), None
    if rate:
        try:
            importi = ripartisci_rate(totali.totale_documento, [r.importo for r in rate])
            rate = list(zip(rate, importi))
        except ErroreRate as errore:
            errore_rate = str(errore)
            rate = [(r, r.importo) for r in rate]
    contesto = {
        "fattura": fattura, "righe": righe, "totali": totali, "rate": rate, "errore_rate": errore_rate,
        "azienda": Azienda.objects.first(),
    }
    return render(request, "fatture/dettaglio.html", contesto)


def emissione(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    fattura = get_object_or_404(Fattura, pk=pk)
    try:
        emetti(fattura)
        messages.success(request, "XML generato e validato sullo schema ufficiale. La fattura ora è bloccata.")
    except ErroreFattura as errore:
        messages.error(request, str(errore))
    return redirect("fattura_dettaglio", pk=pk)


def elimina(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    fattura = get_object_or_404(Fattura, pk=pk)
    if not fattura.modificabile:
        messages.error(request, "Una fattura emessa non si può eliminare.")
        return redirect("fattura_dettaglio", pk=pk)
    fattura.delete()
    messages.success(request, "Bozza eliminata.")
    return redirect("fatture")


def _contenuto_xml(fattura):
    """XML definitivo se la fattura è emessa, altrimenti una versione provvisoria."""
    if fattura.xml:
        return fattura.xml.encode("utf-8")
    return genera_xml(fattura, Azienda.objects.first(), "00000")


def scarica_xml(request, pk):
    fattura = get_object_or_404(Fattura, pk=pk)
    if not fattura.xml:
        messages.error(request, "Emetti la fattura per scaricare l'XML definitivo.")
        return redirect("fattura_dettaglio", pk=pk)
    risposta = HttpResponse(fattura.xml, content_type="application/xml")
    nome = nome_file(Azienda.objects.first(), fattura.progressivo_invio)
    risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return risposta


def anteprima(request, pk):
    fattura = get_object_or_404(Fattura, pk=pk)
    try:
        html = anteprima_html(_contenuto_xml(fattura), versione_schema())
    except ErroreFattura as errore:
        messages.error(request, str(errore))
        return redirect("fattura_dettaglio", pk=pk)
    risposta = HttpResponse(html)
    # Il foglio di stile ufficiale usa stili inline: li consentiamo solo in questa pagina, senza script.
    risposta["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
    return risposta
