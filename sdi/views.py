from django.contrib import messages
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from fatture.models import Fattura
from fatture.xml import anteprima_html, versione_schema

from .forms import ConfigurazionePECForm
from .models import ConfigurazionePEC, FatturaRicevuta
from .pec import ErrorePEC, invia_fattura, leggi_casella, prova_connessione


def impostazioni(request):
    config = ConfigurazionePEC.objects.first()
    form = ConfigurazionePECForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        config = form.save()
        messages.success(request, "Impostazioni PEC salvate.")
        if "prova" in request.POST:
            for nome, ok, dettaglio in prova_connessione(config):
                (messages.success if ok else messages.error)(request, f"{nome}: {dettaglio}")
        return redirect("impostazioni_pec")
    return render(request, "sdi/impostazioni.html", {"form": form, "config": config})


def invia(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    fattura = get_object_or_404(Fattura, pk=pk)
    try:
        nome = invia_fattura(fattura)
        messages.success(
            request,
            f"File {nome} inviato allo SdI via PEC. L'esito (consegna o scarto) arriva in casella: "
            "usa \"Controlla PEC\" per aggiornarlo.",
        )
    except ErrorePEC as errore:
        messages.error(request, str(errore))
    return redirect("fattura_dettaglio", pk=pk)


def _torna(request):
    destinazione = request.POST.get("torna", "")
    if url_has_allowed_host_and_scheme(destinazione, allowed_hosts={request.get_host()}) and destinazione.startswith("/"):
        return redirect(destinazione)
    return redirect("home")


def controlla(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        esito = leggi_casella()
    except ErrorePEC as errore:
        messages.error(request, str(errore))
        return _torna(request)
    riepilogo = (
        f"PEC controllata: {esito.messaggi} nuovi messaggi, {len(esito.notifiche)} notifiche SdI, "
        f"{len(esito.fatture_ricevute)} fatture ricevute."
    )
    messages.success(request, riepilogo)
    if esito.nuovo_indirizzo_sdi:
        messages.info(request, f"Lo SdI ha assegnato l'indirizzo {esito.nuovo_indirizzo_sdi} per i prossimi invii.")
    for errore in esito.errori:
        messages.warning(request, errore)
    return _torna(request)


def ricevute(request):
    return render(request, "sdi/ricevute.html", {"fatture": FatturaRicevuta.objects.all()})


def ricevuta_dettaglio(request, pk):
    fattura = get_object_or_404(FatturaRicevuta, pk=pk)
    return render(request, "sdi/ricevuta_dettaglio.html", {"fattura": fattura})


def ricevuta_anteprima(request, pk):
    fattura = get_object_or_404(FatturaRicevuta, pk=pk)
    if fattura.formato != "FPR12":
        messages.warning(request, "Anteprima disponibile solo per le fatture tra privati (FPR12): scarica il file.")
        return redirect("ricevuta_dettaglio", pk=pk)
    try:
        html = anteprima_html(fattura.xml.encode("utf-8"), versione_schema())
    except Exception:  # noqa: BLE001 - file di terzi: in caso di problemi si offre il download
        messages.error(request, "Impossibile mostrare l'anteprima di questo file: scaricalo.")
        return redirect("ricevuta_dettaglio", pk=pk)
    risposta = HttpResponse(html)
    risposta["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
    return risposta


def ricevuta_file(request, pk):
    fattura = get_object_or_404(FatturaRicevuta, pk=pk)
    risposta = HttpResponse(bytes(fattura.file_originale), content_type="application/octet-stream")
    risposta["Content-Disposition"] = f'attachment; filename="{fattura.nome_file}"'
    return risposta
