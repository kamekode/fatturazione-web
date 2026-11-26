from django import forms
from django.utils import timezone

from catalogo.models import Articolo

from .models import DDT, Movimento, RigaDDT


class MovimentoForm(forms.ModelForm):
    quantita = forms.DecimalField(
        label="Quantità", max_digits=20, decimal_places=4, widget=forms.NumberInput(attrs={"step": "any"}),
        help_text="Per carico e scarico la quantità è sempre positiva. Per la rettifica indica la giacenza effettiva contata.",
    )

    class Meta:
        model = Movimento
        fields = ["articolo", "data", "tipo", "quantita", "descrizione"]
        widgets = {"data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["articolo"].queryset = Articolo.objects.filter(gestito_a_magazzino=True, attivo=True)

    def clean(self):
        dati = super().clean()
        quantita, tipo = dati.get("quantita"), dati.get("tipo")
        if quantita is not None and tipo in (Movimento.Tipo.CARICO, Movimento.Tipo.SCARICO) and quantita <= 0:
            self.add_error("quantita", "Indica una quantità maggiore di zero.")
        if quantita is not None and tipo == Movimento.Tipo.RETTIFICA and quantita < 0:
            self.add_error("quantita", "La giacenza contata non può essere negativa.")
        return dati


class DDTForm(forms.ModelForm):
    numero = forms.IntegerField(
        label="Numero DDT", min_value=1,
        help_text="Proposto in automatico (progressivo per anno, separato dalle fatture).",
    )
    field_order = ["numero", "data", "cliente"]

    class Meta:
        model = DDT
        fields = [
            "cliente", "data", "causale_trasporto", "da_fatturare", "destinazione", "trasporto_a_cura", "vettore",
            "aspetto_beni", "numero_colli", "peso_kg", "inizio_trasporto", "note",
        ]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "inizio_trasporto": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "causale_trasporto": forms.TextInput(attrs={"list": "causali-trasporto"}),
            "destinazione": forms.Textarea(attrs={"rows": 2}),
            "note": forms.Textarea(attrs={"rows": 2}),
            "peso_kg": forms.NumberInput(attrs={"step": "any", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["numero"] = self.instance.numero
        else:
            self.initial["numero"] = DDT.prossimo_numero(timezone.localdate().year)

    def clean(self):
        dati = super().clean()
        data, numero = dati.get("data"), dati.get("numero")
        if data and numero and not self.instance.pk and data.year != timezone.localdate().year and numero == self.initial.get("numero"):
            numero = dati["numero"] = DDT.prossimo_numero(data.year)
        if self.instance.pk and data and data.year != self.instance.anno:
            self.add_error("data", "Non si può spostare il DDT in un altro anno: la numerazione è annuale.")
        if data and numero and DDT.objects.filter(anno=data.year, numero=numero).exclude(pk=self.instance.pk).exists():
            self.add_error("numero", f"Esiste già il DDT {numero}/{data.year}.")
        if dati.get("trasporto_a_cura") == DDT.Trasporto.VETTORE and not dati.get("vettore"):
            self.add_error("vettore", "Indica il vettore.")
        return dati

    def save(self, commit=True):
        self.instance.numero = self.cleaned_data["numero"]
        return super().save(commit)


class RigaDDTForm(forms.ModelForm):
    class Meta:
        model = RigaDDT
        fields = ["articolo", "descrizione", "quantita", "unita_misura", "prezzo_unitario"]
        widgets = {
            "descrizione": forms.TextInput(),
            "quantita": forms.NumberInput(attrs={"step": "any", "min": "0"}),
            "prezzo_unitario": forms.NumberInput(attrs={"step": "any"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["descrizione"].required = False
        self.fields["articolo"].queryset = Articolo.objects.filter(attivo=True)

    def has_changed(self):
        if not self.instance.pk:
            if not any(self.data.get(self.add_prefix(c), "").strip() for c in ("articolo", "descrizione")):
                return False
        return super().has_changed()

    def clean(self):
        dati = super().clean()
        articolo = dati.get("articolo")
        if articolo:
            dati["descrizione"] = dati.get("descrizione") or articolo.descrizione
            dati["unita_misura"] = dati.get("unita_misura") or articolo.unita_misura
            if dati.get("prezzo_unitario") is None:
                dati["prezzo_unitario"] = articolo.prezzo
        if not dati.get("descrizione"):
            self.add_error("descrizione", "Descrizione obbligatoria.")
        for campo in ("descrizione", "unita_misura", "prezzo_unitario"):
            if campo in dati:
                setattr(self.instance, campo, dati[campo])
        return dati


RigheDDTFormSet = forms.inlineformset_factory(
    DDT, RigaDDT, form=RigaDDTForm, extra=0, can_delete=True, min_num=1, validate_min=True
)


class FatturaDifferitaForm(forms.Form):
    data = forms.DateField(
        label="Data della fattura", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="La fattura differita va emessa entro il giorno 15 del mese successivo a quello del DDT più vecchio.",
    )
    ddt = forms.ModelMultipleChoiceField(queryset=DDT.objects.none(), widget=forms.CheckboxSelectMultiple, label="DDT da fatturare")

    def __init__(self, *args, cliente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("data", timezone.localdate())
        coda = DDT.objects.filter(stato=DDT.Stato.CONFERMATO, da_fatturare=True, fattura__isnull=True)
        if cliente is not None:
            coda = coda.filter(cliente=cliente)
        self.fields["ddt"].queryset = coda.order_by("data", "numero")
        self.fields["ddt"].label_from_instance = lambda d: f"{d} - {d.cliente}"
