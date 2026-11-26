"""Operazioni di magazzino, DDT e fattura differita."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from anagrafiche.models import Azienda
from fatture.calcoli import calcola_scadenza
from fatture.codici import TerminiPagamento, TipoDocumento

from .models import DDT, Movimento


class ErroreMagazzino(Exception):
    pass


ALIQUOTA_ORDINARIA = Decimal("22")


def termine_fattura_differita(data_ddt: date) -> date:
    """Giorno 15 del mese successivo a quello del DDT (art. 21, comma 4, lett. a, DPR 633/1972)."""
    ultimo = calendar.monthrange(data_ddt.year, data_ddt.month)[1]
    return date(data_ddt.year, data_ddt.month, ultimo) + timedelta(days=15)


def conferma_ddt(ddt: DDT) -> DDT:
    """Blocca il DDT e scarica dal magazzino gli articoli gestiti a giacenza."""
    if not ddt.modificabile:
        raise ErroreMagazzino("Il DDT è già confermato.")
    righe = list(ddt.righe.select_related("articolo"))
    if not righe:
        raise ErroreMagazzino("Il DDT non ha righe.")
    with transaction.atomic():
        for riga in righe:
            if riga.articolo and riga.articolo.gestito_a_magazzino and riga.quantita:
                Movimento.objects.create(
                    articolo=riga.articolo, data=ddt.data, tipo=Movimento.Tipo.SCARICO, quantita=-riga.quantita,
                    descrizione=f"DDT {ddt.numero_documento} - {ddt.cliente}"[:200], ddt=ddt,
                )
        ddt.stato = DDT.Stato.CONFERMATO
        ddt.save(update_fields=["stato"])
    return ddt


def riapri_ddt(ddt: DDT) -> DDT:
    """Riporta in bozza un DDT non ancora fatturato, annullando gli scarichi."""
    if ddt.modificabile:
        raise ErroreMagazzino("Il DDT è già in bozza.")
    if ddt.fattura_id:
        raise ErroreMagazzino(f"Il DDT è già in fattura ({ddt.fattura.numero_documento}): elimina prima quella bozza.")
    with transaction.atomic():
        ddt.movimenti.all().delete()
        ddt.stato = DDT.Stato.BOZZA
        ddt.save(update_fields=["stato"])
    return ddt


def _aliquota_e_natura(articolo, azienda):
    if articolo:
        return articolo.aliquota_iva, articolo.natura
    if azienda.forfettario:
        return Decimal("0"), "N2.2"
    return ALIQUOTA_ORDINARIA, ""


def crea_fattura_differita(elenco_ddt, data=None):
    """Crea una fattura differita (TD24) in bozza con le righe dei DDT scelti.

    Restituisce (fattura, avvisi). La fattura resta modificabile come ogni bozza.
    """
    from fatture.models import Fattura, RigaFattura

    elenco_ddt = sorted(elenco_ddt, key=lambda d: (d.data, d.anno, d.numero))
    if not elenco_ddt:
        raise ErroreMagazzino("Scegli almeno un DDT.")
    if len({d.cliente_id for d in elenco_ddt}) > 1:
        raise ErroreMagazzino("I DDT di una fattura differita devono essere dello stesso cliente.")
    for ddt in elenco_ddt:
        if not ddt.fatturabile:
            raise ErroreMagazzino(f"Il DDT {ddt.numero_documento} non è fatturabile (bozza, già fatturato o non da fatturare).")
    azienda = Azienda.objects.first()
    if azienda is None:
        raise ErroreMagazzino("Compila prima i dati azienda.")
    data = data or date.today()
    avvisi = []
    if any(d.data > data for d in elenco_ddt):
        raise ErroreMagazzino("La data della fattura non può precedere quella dei DDT.")
    termine = termine_fattura_differita(elenco_ddt[0].data)
    if data > termine:
        avvisi.append(
            f"La fattura differita andava emessa entro il {termine:%d/%m/%Y} (giorno 15 del mese successivo "
            f"al DDT {elenco_ddt[0].numero_documento})."
        )
    with transaction.atomic():
        fattura = Fattura.objects.create(
            cliente=elenco_ddt[0].cliente, tipo_documento=TipoDocumento.DIFFERITA, data=data,
            termini_pagamento=TerminiPagamento.GG30, data_scadenza=calcola_scadenza(data, TerminiPagamento.GG30),
        )
        ordine = 0
        for ddt in elenco_ddt:
            for riga in ddt.righe.select_related("articolo"):
                prezzo = riga.prezzo_unitario
                if prezzo is None:
                    prezzo = riga.articolo.prezzo if riga.articolo else Decimal("0")
                    avvisi.append(f"DDT {ddt.numero_documento}, \"{riga.descrizione[:40]}\": prezzo mancante, controlla la riga.")
                aliquota, natura = _aliquota_e_natura(riga.articolo, azienda)
                RigaFattura.objects.create(
                    fattura=fattura, articolo=riga.articolo, descrizione=riga.descrizione, quantita=riga.quantita,
                    unita_misura=riga.unita_misura, prezzo_unitario=prezzo, aliquota_iva=aliquota, natura=natura,
                    ddt=ddt, ordine=ordine,
                )
                ordine += 1
            ddt.fattura = fattura
            ddt.save(update_fields=["fattura"])
    return fattura, avvisi


def scarica_fattura(fattura):
    """All'emissione, scarica gli articoli a magazzino venduti senza DDT (già scaricati dal DDT)."""
    for riga in fattura.righe.select_related("articolo"):
        if riga.articolo and riga.articolo.gestito_a_magazzino and riga.ddt_id is None and riga.quantita:
            segno = 1 if fattura.tipo_documento == TipoDocumento.NOTA_CREDITO else -1
            Movimento.objects.create(
                articolo=riga.articolo, data=fattura.data,
                tipo=Movimento.Tipo.CARICO if segno > 0 else Movimento.Tipo.SCARICO,
                quantita=segno * riga.quantita,
                descrizione=f"Fattura {fattura.numero_documento} - {fattura.cliente}"[:200], fattura=fattura,
            )


def annulla_scarichi_fattura(fattura):
    fattura.movimenti.all().delete()
