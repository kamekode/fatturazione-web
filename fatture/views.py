from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from anagrafiche.models import Azienda

from .calcoli import calcola_totali
from .forms import FatturaForm, RigheFormSet
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
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            fattura = form.save()
            formset.instance = fattura
            righe = formset.save(commit=False)
            for oggetto in formset.deleted_objects:
                oggetto.delete()
            for ordine, riga in enumerate(righe):
                riga.ordine = ordine
                riga.save()
        messages.success(request, f"Fattura {fattura.numero_documento} salvata come bozza.")
        return redirect("fattura_dettaglio", pk=fattura.pk)
    return render(request, "fatture/form.html", {"form": form, "formset": formset, "fattura": fattura if pk else None})


def dettaglio(request, pk):
    fattura = get_object_or_404(Fattura.objects.select_related("cliente"), pk=pk)
    righe = list(fattura.righe.all())
    return render(request, "fatture/dettaglio.html", {"fattura": fattura, "righe": righe, "totali": calcola_totali(righe)})


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
