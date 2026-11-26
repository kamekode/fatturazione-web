from django import forms

MAX_UPLOAD = 50 * 1024 * 1024


class ImportaFlextaxForm(forms.Form):
    archivio = forms.FileField(
        label="ZIP delle fatture (o un singolo XML)", required=False,
        help_text="L'archivio che Flextax esporta con le fatture: vengono letti solo i file .xml e .xml.p7m, i PDF sono ignorati.",
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,.xml,.p7m"}),
    )
    elenco = forms.FileField(
        label="CSV dell'elenco documenti (facoltativo)", required=False,
        help_text="Serve per importare gli incassi (acconti e date di pagamento). Va bene anche caricarlo dopo le fatture.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def clean(self):
        dati = super().clean()
        if not dati.get("archivio") and not dati.get("elenco"):
            raise forms.ValidationError("Carica almeno un file.")
        for nome in ("archivio", "elenco"):
            file = dati.get(nome)
            if file and file.size > MAX_UPLOAD:
                self.add_error(nome, "File troppo grande (massimo 50 MB).")
        return dati
