from django.contrib import messages
from django.db import transaction
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from anagrafiche.models import Azienda, Cliente
from catalogo.models import Articolo

from .forms import DDTForm, FatturaDifferitaForm, MovimentoForm, RigheDDTFormSet
from .models import DDT, Movimento, giacenza
from .servizi import ErroreMagazzino, conferma_ddt, crea_fattura_differita, riapri_ddt, termine_fattura_differita


def _solo_post(request):
    return None if request.method == "POST" else HttpResponseNotAllowed(["POST"])


# --- Magazzino ----------------------------------------------------------------------


def giacenze(request):
    articoli = Articolo.objects.filter(gestito_a_magazzino=True).annotate(
        giacenza=Coalesce(Sum("movimenti__quantita"), Value(0), output_field=DecimalField(max_digits=20, decimal_places=4))
    )
    return render(request, "magazzino/giacenze.html", {"articoli": articoli})


def movimenti(request, articolo_pk):
    articolo = get_object_or_404(Articolo, pk=articolo_pk)
    elenco = articolo.movimenti.select_related("ddt", "fattura")
    return render(request, "magazzino/movimenti.html", {"articolo": articolo, "movimenti": elenco, "giacenza": giacenza(articolo)})


def movimento_nuovo(request):
    iniziali = {"articolo": request.GET.get("articolo")} if request.GET.get("articolo") else {}
    form = MovimentoForm(request.POST or None, initial=iniziali)
    if request.method == "POST" and form.is_valid():
        movimento = form.save(commit=False)
        if movimento.tipo == Movimento.Tipo.SCARICO:
            movimento.quantita = -movimento.quantita
        elif movimento.tipo == Movimento.Tipo.RETTIFICA:
            # Si registra la differenza tra la giacenza contata e quella calcolata a quella data.
            contata = movimento.quantita
            movimento.quantita = contata - giacenza(movimento.articolo, al=movimento.data)
            movimento.descrizione = movimento.descrizione or f"Inventario: giacenza contata {contata.normalize():f}"
            if not movimento.quantita:
                messages.info(request, "La giacenza contata coincide con quella calcolata: nessuna rettifica necessaria.")
                return redirect("movimenti", articolo_pk=movimento.articolo_id)
        movimento.save()
        messages.success(request, "Movimento registrato.")
        return redirect("movimenti", articolo_pk=movimento.articolo_id)
    if not Articolo.objects.filter(gestito_a_magazzino=True).exists():
        messages.warning(request, "Nessun articolo è gestito a magazzino: attiva l'opzione nella scheda dell'articolo.")
    return render(request, "magazzino/movimento_form.html", {"form": form})


# --- DDT ----------------------------------------------------------------------------


def ddt_elenco(request):
    elenco = DDT.objects.select_related("cliente", "fattura")
    da_fatturare = DDT.objects.filter(stato=DDT.Stato.CONFERMATO, da_fatturare=True, fattura__isnull=True).exists()
    return render(request, "magazzino/ddt_elenco.html", {"elenco": elenco, "da_fatturare": da_fatturare})


def ddt_modifica(request, pk=None):
    ddt = get_object_or_404(DDT, pk=pk) if pk else DDT()
    if pk and not ddt.modificabile:
        messages.error(request, "Un DDT confermato non si può modificare: riportalo in bozza.")
        return redirect("ddt_dettaglio", pk=pk)
    if not Azienda.objects.exists():
        messages.warning(request, "Prima di creare DDT compila i dati della tua azienda.")
        return redirect("azienda")
    form = DDTForm(request.POST or None, instance=ddt)
    formset = RigheDDTFormSet(request.POST or None, instance=ddt, prefix="righe")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            ddt = form.save()
            formset.instance = ddt
            righe = formset.save(commit=False)
            for oggetto in formset.deleted_objects:
                oggetto.delete()
            for ordine, riga in enumerate(righe):
                riga.ordine = ordine
                riga.save()
        messages.success(request, f"DDT {ddt.numero_documento} salvato come bozza.")
        return redirect("ddt_dettaglio", pk=ddt.pk)
    articoli = {
        str(a.pk): {"descrizione": a.descrizione, "unita_misura": a.unita_misura, "prezzo": f"{a.prezzo.normalize():f}"}
        for a in Articolo.objects.filter(attivo=True)
    }
    contesto = {"form": form, "formset": formset, "ddt": ddt if pk else None, "articoli": articoli}
    return render(request, "magazzino/ddt_form.html", contesto)


def ddt_dettaglio(request, pk):
    ddt = get_object_or_404(DDT.objects.select_related("cliente", "fattura"), pk=pk)
    contesto = {"ddt": ddt, "righe": ddt.righe.select_related("articolo"), "termine": termine_fattura_differita(ddt.data)}
    return render(request, "magazzino/ddt_dettaglio.html", contesto)


def ddt_stampa(request, pk):
    ddt = get_object_or_404(DDT.objects.select_related("cliente"), pk=pk)
    contesto = {"ddt": ddt, "righe": ddt.righe.all(), "azienda": Azienda.objects.first()}
    return render(request, "magazzino/ddt_stampa.html", contesto)


def ddt_pdf(request, pk):
    from .pdf import ddt_pdf as genera

    ddt = get_object_or_404(DDT.objects.select_related("cliente"), pk=pk)
    risposta = HttpResponse(genera(ddt, Azienda.objects.first()), content_type="application/pdf")
    disposizione = "inline" if request.GET.get("apri") else "attachment"
    risposta["Content-Disposition"] = f'{disposizione}; filename="DDT_{ddt.anno}_{ddt.numero}.pdf"'
    return risposta


def ddt_conferma(request, pk):
    if risposta := _solo_post(request):
        return risposta
    ddt = get_object_or_404(DDT, pk=pk)
    try:
        conferma_ddt(ddt)
        messages.success(request, "DDT confermato: gli articoli gestiti a magazzino sono stati scaricati.")
    except ErroreMagazzino as errore:
        messages.error(request, str(errore))
    return redirect("ddt_dettaglio", pk=pk)


def ddt_riapri(request, pk):
    if risposta := _solo_post(request):
        return risposta
    ddt = get_object_or_404(DDT, pk=pk)
    try:
        riapri_ddt(ddt)
        messages.success(request, "DDT riportato in bozza: gli scarichi di magazzino sono stati annullati.")
    except ErroreMagazzino as errore:
        messages.error(request, str(errore))
    return redirect("ddt_dettaglio", pk=pk)


def ddt_elimina(request, pk):
    if risposta := _solo_post(request):
        return risposta
    ddt = get_object_or_404(DDT, pk=pk)
    if not ddt.modificabile:
        messages.error(request, "Si può eliminare solo un DDT in bozza.")
        return redirect("ddt_dettaglio", pk=pk)
    ddt.delete()
    messages.success(request, "Bozza DDT eliminata.")
    return redirect("ddt_elenco")


def fattura_differita(request):
    cliente = None
    if request.GET.get("cliente"):
        cliente = get_object_or_404(Cliente, pk=request.GET["cliente"])
    form = FatturaDifferitaForm(request.POST or None, cliente=cliente)
    if request.method == "POST" and form.is_valid():
        try:
            fattura, avvisi = crea_fattura_differita(list(form.cleaned_data["ddt"]), form.cleaned_data["data"])
        except ErroreMagazzino as errore:
            form.add_error(None, str(errore))
        else:
            for avviso in avvisi:
                messages.warning(request, avviso)
            messages.success(request, f"Fattura differita {fattura.numero_documento} creata in bozza: controllala ed emettila.")
            return redirect("fattura_dettaglio", pk=fattura.pk)
    clienti = Cliente.objects.filter(
        ddt__stato=DDT.Stato.CONFERMATO, ddt__da_fatturare=True, ddt__fattura__isnull=True
    ).distinct()
    return render(request, "magazzino/fattura_differita.html", {"form": form, "cliente": cliente, "clienti": clienti})
