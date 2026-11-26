from django import forms

from .models import Articolo


class ArticoloForm(forms.ModelForm):
    class Meta:
        model = Articolo
        fields = ["codice", "descrizione", "tipo", "unita_misura", "prezzo", "aliquota_iva", "natura", "attivo"]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2}),
            "prezzo": forms.NumberInput(attrs={"step": "any"}),
            "aliquota_iva": forms.NumberInput(attrs={"step": "any", "min": "0"}),
        }

    def clean(self):
        dati = super().clean()
        if dati.get("aliquota_iva") == 0 and not dati.get("natura"):
            self.add_error("natura", "Con aliquota 0 va indicata la natura (forfettario: N2.2).")
        return dati
