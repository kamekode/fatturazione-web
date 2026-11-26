from django import forms

from anagrafiche.models import Azienda

from .models import Fattura, RigaFattura


class FatturaForm(forms.ModelForm):
    class Meta:
        model = Fattura
        fields = ["cliente", "tipo_documento", "data", "causale", "condizioni_pagamento", "modalita_pagamento", "data_scadenza"]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_scadenza": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "causale": forms.Textarea(attrs={"rows": 2}),
        }


class RigaForm(forms.ModelForm):
    class Meta:
        model = RigaFattura
        fields = ["articolo", "descrizione", "quantita", "unita_misura", "prezzo_unitario", "aliquota_iva", "natura"]
        widgets = {"descrizione": forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["descrizione"].required = False
        self.fields["prezzo_unitario"].required = False
        if not self.instance.pk:
            azienda = Azienda.objects.first()
            if azienda and azienda.forfettario:
                self.initial.setdefault("aliquota_iva", 0)
                self.initial.setdefault("natura", "N2.2")

    def has_changed(self):
        # Una riga vuota (senza articolo, descrizione e prezzo) viene ignorata anche se
        # aliquota e natura hanno i valori predefiniti del forfettario.
        if not self.instance.pk:
            campi = ("articolo", "descrizione", "prezzo_unitario")
            if not any(self.data.get(self.add_prefix(c), "").strip() for c in campi):
                return False
        return super().has_changed()

    def clean(self):
        dati = super().clean()
        articolo = dati.get("articolo")
        if articolo:
            # Se la riga parte da un articolo, i campi vuoti prendono i suoi valori.
            dati["descrizione"] = dati.get("descrizione") or articolo.descrizione
            if dati.get("prezzo_unitario") is None:
                dati["prezzo_unitario"] = articolo.prezzo
            dati["unita_misura"] = dati.get("unita_misura") or articolo.unita_misura
        if not dati.get("descrizione"):
            self.add_error("descrizione", "Descrizione obbligatoria.")
        if dati.get("prezzo_unitario") is None:
            self.add_error("prezzo_unitario", "Prezzo obbligatorio.")
        for campo in ("descrizione", "prezzo_unitario", "unita_misura"):
            if campo in dati:
                setattr(self.instance, campo, dati[campo])
        return dati


RigheFormSet = forms.inlineformset_factory(
    Fattura, RigaFattura, form=RigaForm, extra=3, can_delete=True, min_num=1, validate_min=True
)
