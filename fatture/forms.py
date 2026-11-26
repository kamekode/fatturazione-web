from django import forms

from anagrafiche.models import Azienda

from .calcoli import calcola_scadenza
from .codici import CondizioniPagamento, TerminiPagamento
from .models import Fattura, Rata, RigaFattura


class FatturaForm(forms.ModelForm):
    class Meta:
        model = Fattura
        fields = [
            "cliente", "tipo_documento", "data", "causale", "modalita_pagamento", "condizioni_pagamento",
            "termini_pagamento", "data_scadenza", "numero_rate",
        ]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_scadenza": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "causale": forms.Textarea(attrs={"rows": 2}),
            "numero_rate": forms.NumberInput(attrs={"min": 2, "max": 36}),
        }

    def clean(self):
        dati = super().clean()
        data = dati.get("data")
        termini = dati.get("termini_pagamento")
        a_rate = dati.get("condizioni_pagamento") == CondizioniPagamento.RATE
        if a_rate:
            # Con le rate le scadenze stanno sulle singole rate.
            dati["data_scadenza"] = None
        elif termini == TerminiPagamento.LIBERA:
            if not dati.get("data_scadenza"):
                self.add_error("data_scadenza", "Indica la data di scadenza.")
        elif data and termini:
            dati["data_scadenza"] = calcola_scadenza(data, termini)
        if not a_rate:
            dati["numero_rate"] = None
        elif dati.get("numero_rate") is not None and not 2 <= dati["numero_rate"] <= 36:
            self.add_error("numero_rate", "Da 2 a 36 rate.")
        return dati


class RigaForm(forms.ModelForm):
    class Meta:
        model = RigaFattura
        fields = ["articolo", "descrizione", "quantita", "unita_misura", "prezzo_unitario", "aliquota_iva", "natura"]
        widgets = {
            "descrizione": forms.TextInput(),
            # step "any": le frecce cambiano di 1 ma si possono scrivere anche i decimali.
            "quantita": forms.NumberInput(attrs={"step": "any", "min": "0"}),
            "prezzo_unitario": forms.NumberInput(attrs={"step": "any"}),
            "aliquota_iva": forms.NumberInput(attrs={"step": "any", "min": "0"}),
        }

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
    Fattura, RigaFattura, form=RigaForm, extra=0, can_delete=True, min_num=1, validate_min=True
)


class RataForm(forms.ModelForm):
    class Meta:
        model = Rata
        fields = ["data_scadenza", "importo"]
        widgets = {
            "data_scadenza": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "importo": forms.NumberInput(attrs={"step": "any", "min": "0"}),
        }

    def has_changed(self):
        if not self.instance.pk and not any(
            self.data.get(self.add_prefix(c), "").strip() for c in ("data_scadenza", "importo")
        ):
            return False
        return super().has_changed()


RateFormSet = forms.inlineformset_factory(Fattura, Rata, form=RataForm, extra=0, can_delete=True)
