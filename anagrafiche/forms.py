from django import forms

from .models import Azienda, Cliente


class AziendaForm(forms.ModelForm):
    class Meta:
        model = Azienda
        fields = [
            "denominazione", "nome", "cognome", "partita_iva", "codice_fiscale", "regime_fiscale",
            "indirizzo", "numero_civico", "cap", "comune", "provincia", "nazione",
            "telefono", "email", "pec", "iban", "istituto_finanziario", "riferimento_normativo",
        ]


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "denominazione", "nome", "cognome", "partita_iva", "codice_fiscale",
            "indirizzo", "numero_civico", "cap", "comune", "provincia", "nazione",
            "codice_destinatario", "pec", "email", "telefono", "note",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}
