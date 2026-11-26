from datetime import date
from decimal import Decimal

from anagrafiche.models import Azienda, Cliente
from fatture.models import Fattura, RigaFattura

PIVA_AZIENDA = "12345678903"
CF_AZIENDA = "RSSMRA85T10A562S"


def crea_azienda(**campi):
    dati = dict(
        nome="Mario", cognome="Rossi", partita_iva=PIVA_AZIENDA, codice_fiscale=CF_AZIENDA,
        indirizzo="Via Roma", numero_civico="1", cap="00100", comune="Roma", provincia="RM",
        email="mario@example.com", iban="IT60X0542811101000000123456",
    )
    dati.update(campi)
    return Azienda.objects.create(**dati)


def crea_cliente(**campi):
    dati = dict(
        denominazione="Cliente Srl", partita_iva="01234567897", indirizzo="Via Milano 2",
        cap="20100", comune="Milano", provincia="MI", codice_destinatario="ABC1234",
    )
    dati.update(campi)
    cliente = Cliente(**dati)
    cliente.full_clean()
    cliente.save()
    return cliente


def crea_fattura(cliente, righe=((Decimal("1"), Decimal("100.00")),), **campi):
    campi.setdefault("bollo_a_carico_cliente", False)
    fattura = Fattura.objects.create(cliente=cliente, data=campi.pop("data", date(2026, 11, 26)), **campi)
    for i, riga in enumerate(righe):
        quantita, prezzo, aliquota, natura = (tuple(riga) + (Decimal("0"), "N2.2")[len(riga) - 2 :])[:4]
        RigaFattura.objects.create(
            fattura=fattura, descrizione=f"Consulenza {i + 1}", quantita=quantita,
            prezzo_unitario=prezzo, aliquota_iva=aliquota, natura=natura, ordine=i,
        )
    return fattura
