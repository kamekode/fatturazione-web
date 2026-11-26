from django.shortcuts import render

from anagrafiche.models import Azienda, Cliente
from fatture.models import Fattura


def home(request):
    contesto = {
        "azienda": Azienda.objects.first(),
        "num_clienti": Cliente.objects.count(),
        "num_fatture": Fattura.objects.count(),
        "ultime_fatture": Fattura.objects.select_related("cliente").order_by("-data", "-numero")[:5],
    }
    return render(request, "core/home.html", contesto)
