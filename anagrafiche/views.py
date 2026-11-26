from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AziendaForm, ClienteForm
from .models import Azienda, Cliente


def azienda(request):
    istanza = Azienda.objects.first()
    form = AziendaForm(request.POST or None, instance=istanza)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dati azienda salvati.")
        return redirect("home")
    return render(request, "anagrafiche/azienda.html", {"form": form})


def clienti(request):
    q = request.GET.get("q", "").strip()
    elenco = Cliente.objects.all()
    if q:
        elenco = elenco.filter(
            Q(denominazione__icontains=q) | Q(cognome__icontains=q) | Q(nome__icontains=q)
            | Q(partita_iva__icontains=q) | Q(codice_fiscale__icontains=q)
        )
    return render(request, "anagrafiche/clienti.html", {"clienti": elenco, "q": q})


def cliente_modifica(request, pk=None):
    istanza = get_object_or_404(Cliente, pk=pk) if pk else None
    form = ClienteForm(request.POST or None, instance=istanza)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cliente salvato.")
        return redirect("clienti")
    return render(request, "anagrafiche/cliente_form.html", {"form": form, "cliente": istanza})
