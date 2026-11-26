from django.db import transaction

from anagrafiche.models import Azienda

from magazzino.servizi import annulla_scarichi_fattura, scarica_fattura

from .models import Contatore, Fattura
from .xml import ErroreFattura, genera_xml, progressivo_da_numero, valida, versione_schema


def emetti(fattura: Fattura) -> Fattura:
    """Genera l'XML, lo valida sullo schema ufficiale e blocca la fattura.

    Se lo schema segnala errori la fattura resta in bozza e viene sollevata ErroreFattura.
    """
    if not fattura.modificabile:
        raise ErroreFattura("La fattura è già stata emessa.")
    azienda = Azienda.objects.first()
    if azienda is None:
        raise ErroreFattura("Compilare prima i dati azienda.")
    versione = versione_schema()
    with transaction.atomic():
        progressivo = progressivo_da_numero(Contatore.prossimo("progressivo_invio"))
        contenuto = genera_xml(fattura, azienda, progressivo, versione)
        errori = valida(contenuto, versione)
        if errori:
            # L'eccezione annulla la transazione, compreso l'incremento del progressivo.
            raise ErroreFattura("Il file non supera la validazione dello schema: " + "; ".join(errori[:5]))
        fattura.xml = contenuto.decode("utf-8")
        fattura.progressivo_invio = progressivo
        fattura.stato = Fattura.Stato.EMESSA
        fattura.save(update_fields=["xml", "progressivo_invio", "stato", "modificata_il"])
        scarica_fattura(fattura)
    return fattura


def riporta_in_bozza(fattura: Fattura) -> Fattura:
    """Dopo uno scarto la fattura si considera non emessa: torna modificabile con lo stesso numero.

    Al nuovo invio riceverà un nuovo progressivo, quindi un nuovo nome file.
    """
    if fattura.stato != Fattura.Stato.SCARTATA:
        raise ErroreFattura("Solo una fattura scartata dallo SdI può tornare in bozza.")
    annulla_scarichi_fattura(fattura)
    fattura.stato = Fattura.Stato.BOZZA
    fattura.xml = ""
    fattura.progressivo_invio = ""
    fattura.save(update_fields=["stato", "xml", "progressivo_invio", "modificata_il"])
    return fattura
