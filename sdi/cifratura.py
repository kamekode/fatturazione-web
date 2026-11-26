"""Cifratura delle credenziali salvate nel database (es. password della PEC).

La chiave arriva da FATTURAZIONE_CHIAVE_CIFRATURA (chiave Fernet). Se manca,
viene derivata da DJANGO_SECRET_KEY: in quel caso cambiare la SECRET_KEY rende
illeggibili le password salvate, che andranno reinserite.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    chiave = os.environ.get("FATTURAZIONE_CHIAVE_CIFRATURA")
    if not chiave:
        derivata = hashlib.sha256(("fatturazione-pec:" + settings.SECRET_KEY).encode()).digest()
        chiave = base64.urlsafe_b64encode(derivata)
    return Fernet(chiave)


def cifra(testo: str) -> str:
    return _fernet().encrypt(testo.encode()).decode() if testo else ""


def decifra(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
