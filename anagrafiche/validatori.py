"""Controlli formali su partita IVA, codice fiscale e altri dati anagrafici."""

import re

from django.core.exceptions import ValidationError

_CF_PERSONA = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")
_CF_DISPARI = {
    **dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21])),
    **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23])),
}


def partita_iva_valida(piva: str) -> bool:
    """Verifica la cifra di controllo di una partita IVA italiana (11 cifre)."""
    if not re.fullmatch(r"\d{11}", piva or ""):
        return False
    somma = 0
    for i, c in enumerate(piva[:10]):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        somma += n
    return (10 - somma % 10) % 10 == int(piva[10])


def codice_fiscale_persona_valido(cf: str) -> bool:
    cf = (cf or "").upper()
    if not _CF_PERSONA.fullmatch(cf):
        return False
    somma = 0
    for i, c in enumerate(cf[:15]):
        if i % 2 == 0:  # posizioni dispari (1, 3, 5...)
            somma += _CF_DISPARI[c]
        else:
            somma += int(c) if c.isdigit() else ord(c) - ord("A")
    return chr(ord("A") + somma % 26) == cf[15]


def valida_partita_iva(valore):
    if not partita_iva_valida(valore):
        raise ValidationError("Partita IVA non valida: servono 11 cifre con cifra di controllo corretta.")


def valida_codice_fiscale(valore):
    """Accetta il codice fiscale di una persona (16 caratteri) o di un ente (11 cifre)."""
    valore = (valore or "").upper()
    if len(valore) == 11 and partita_iva_valida(valore):
        return
    if len(valore) == 16 and codice_fiscale_persona_valido(valore):
        return
    raise ValidationError("Codice fiscale non valido.")


def valida_codice_destinatario(valore):
    if not re.fullmatch(r"[A-Z0-9]{7}", valore or ""):
        raise ValidationError("Il codice destinatario per i privati è di 7 caratteri (lettere maiuscole e cifre).")
