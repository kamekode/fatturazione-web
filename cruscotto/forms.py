from django import forms

from fatture.models import Incasso

from .models import ProfiloFiscale, Versamento

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
NUMERO = forms.NumberInput(attrs={"step": "any", "min": "0"})


class ProfiloFiscaleForm(forms.ModelForm):
    class Meta:
        model = ProfiloFiscale
        fields = [
            "codice_ateco", "coefficiente_redditivita", "aliquota_imposta", "anno_inizio_attivita",
            "gestione_previdenziale", "reddito_minimale", "contributi_fissi", "aliquota_contributi", "riduzione_contributiva",
        ]
        widgets = {
            "coefficiente_redditivita": NUMERO, "aliquota_imposta": NUMERO, "reddito_minimale": NUMERO,
            "contributi_fissi": NUMERO, "aliquota_contributi": NUMERO,
        }


class VersamentoForm(forms.ModelForm):
    class Meta:
        model = Versamento
        fields = ["data", "tipo", "anno_riferimento", "importo", "note"]
        widgets = {"data": DATA, "importo": NUMERO}


class IncassoForm(forms.ModelForm):
    class Meta:
        model = Incasso
        fields = ["data", "importo", "note"]
        widgets = {"data": DATA, "importo": NUMERO}
