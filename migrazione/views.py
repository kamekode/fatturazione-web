from django.shortcuts import render

from fatture.models import Fattura

from .flextax import ErroreImportazione, Resoconto, file_xml_da_zip, importa_fatture, importa_incassi
from .forms import ImportaFlextaxForm


def importa_flextax(request):
    form = ImportaFlextaxForm(request.POST, request.FILES) if request.method == "POST" else ImportaFlextaxForm()
    resoconto, errore = None, None
    if form.is_bound and form.is_valid():
        resoconto = Resoconto()
        try:
            archivio = form.cleaned_data.get("archivio")
            if archivio:
                contenuto = archivio.read()
                if archivio.name.lower().endswith(".zip"):
                    file_xml, resoconto.file_ignorati = file_xml_da_zip(contenuto)
                else:
                    file_xml = [(archivio.name, contenuto)]
                importa_fatture(file_xml, resoconto)
            elenco = form.cleaned_data.get("elenco")
            if elenco:
                importa_incassi(elenco.read(), resoconto)
        except ErroreImportazione as e:
            errore = str(e)
        form = ImportaFlextaxForm()
    anno = max(Fattura.objects.values_list("anno", flat=True), default=None)
    contesto = {
        "form": form, "resoconto": resoconto, "errore": errore,
        "prossimo_numero": f"{Fattura.prossimo_numero(anno)}/{anno}" if anno else None,
    }
    return render(request, "migrazione/flextax.html", contesto)
