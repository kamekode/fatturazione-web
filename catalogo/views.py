from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ArticoloForm
from .models import Articolo


def articoli(request):
    return render(request, "catalogo/articoli.html", {"articoli": Articolo.objects.all()})


def articolo_modifica(request, pk=None):
    istanza = get_object_or_404(Articolo, pk=pk) if pk else None
    iniziali = {}
    if istanza is None:
        from anagrafiche.models import Azienda

        azienda = Azienda.objects.first()
        if azienda and azienda.forfettario:
            iniziali = {"aliquota_iva": 0, "natura": "N2.2"}
    form = ArticoloForm(request.POST or None, instance=istanza, initial=iniziali)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Articolo salvato.")
        return redirect("articoli")
    return render(request, "catalogo/articolo_form.html", {"form": form, "articolo": istanza})
