from django import forms

from .models import ConfigurazionePEC


class ConfigurazionePECForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        required=False,
        help_text="Viene salvata cifrata. Lascia vuoto per mantenere quella attuale.",
    )

    class Meta:
        model = ConfigurazionePEC
        fields = [
            "indirizzo", "username", "password", "smtp_host", "smtp_porta", "smtp_sicurezza",
            "imap_host", "imap_porta", "imap_sicurezza", "imap_cartella", "indirizzo_sdi",
        ]

    def clean(self):
        dati = super().clean()
        if not dati.get("password") and not self.instance.password_cifrata:
            self.add_error("password", "Inserisci la password della casella PEC.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("password"):
            self.instance.password = self.cleaned_data["password"]
        return super().save(commit)
