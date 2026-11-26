# Fatturazione Web

Software web per la fatturazione elettronica: emissione delle fatture in formato FatturaPA,
invio e ricezione tramite il Sistema di Interscambio (SdI), magazzino e DDT, scadenziario e
cruscotto con previsione delle tasse.

## Stato del progetto

| Passo | Contenuto | Stato |
|---|---|---|
| 1 | Base, accesso protetto, anagrafiche, articoli, termini di pagamento e rate, XML FatturaPA validato | ✅ |
| 2 | Invio e ricezione SdI via PEC (poi SDICoop) | ✅ PEC |
| 3 | Magazzino, DDT, fattura differita, migrazione dati | da fare |
| 4 | Scadenziario e cruscotto con previsione tasse | da fare |

## Cosa fa oggi

- **Accesso protetto**: tutte le pagine richiedono il login. Password di almeno 12 caratteri salvate con Argon2,
  blocco per un'ora dopo 5 tentativi errati, sessione che scade dopo 8 ore, cookie sicuri e HTTPS obbligatorio
  in produzione, intestazioni di sicurezza (CSP, HSTS, anti-clickjacking), nessuna registrazione pubblica.
- **Dati azienda** (cedente/prestatore) con regime fiscale, predefinito forfettario (RF19).
- **Clienti** con controllo di partita IVA e codice fiscale, codice destinatario SdI o PEC, clienti esteri.
- **Articoli e servizi** con prezzo, aliquota e natura predefiniti.
- **Fatture** con numerazione progressiva annuale, righe da articolo o libere, calcolo di totali,
  riepilogo IVA e bollo virtuale (2 € oltre 77,47 € di operazioni senza IVA).
- **Pagamento**: termini 30/60/90 gg data fattura o fine mese con scadenza calcolata, data specifica,
  oppure pagamento a rate con scadenze generate e modificabili (una riga DettaglioPagamento per rata).
- **Bollo a carico del cliente** (spunta in fattura, attiva di default): i 2 € diventano una riga "Imposta di bollo"
  con natura N1 e entrano nel totale. Totale aggiornato in tempo reale durante la compilazione.
- **Testo a piè di fattura** personalizzabile in Dati azienda, riportato nella Causale dell'XML.
- **XML FatturaPA (FPR12)** generato e validato sugli schemi ufficiali 1.2.3 e 1.2.4 prima dell'emissione,
  con nome file e progressivo di invio conformi. Anteprima con il foglio di stile ufficiale.

Una fattura emessa non si può più modificare né eliminare.

### Invio e ricezione con lo SdI via PEC

- **Impostazioni PEC**: indirizzo, utente, password (salvata cifrata), server SMTP e IMAP. Valori proposti per Aruba
  (`smtps.pec.aruba.it:465`, `imaps.pec.aruba.it:993`, SSL), con pulsante per provare la connessione.
- **Invio**: la fattura emessa parte come allegato PEC verso lo SdI. Il primo invio va a `sdi01@pec.fatturapa.it`;
  quando lo SdI risponde da un altro indirizzo `sdiNN@pec.fatturapa.it`, quello viene salvato per gli invii successivi
  (regola delle specifiche tecniche SdI, servizio PEC). L'indirizzo resta modificabile.
- **Controlla PEC** legge i nuovi messaggi (senza segnarli come letti) e riconosce solo quelli dello SdI:
  - ricevuta di consegna (RC) → fattura *Consegnata*;
  - notifica di scarto (NS) → fattura *Scartata*, con gli errori; si può riportare in bozza, correggere e riemettere
    con lo stesso numero;
  - mancata consegna (MC) → *Non recapitata*: la fattura è emessa e disponibile al cliente nella sua area riservata;
  - fatture dei fornitori (anche firmate `.p7m`) → sezione **Ricevute**, con anteprima e file originale conservato.
- Il controllo si può pianificare: `python manage.py controlla_pec` (ad esempio con l'Utilità di pianificazione di Windows).

Le fonti ufficiali usate (schemi, fogli di stile, esempi) sono elencate in [`schemi/FONTI.md`](schemi/FONTI.md).

## Avvio in locale

Serve Python 3.12 o successivo e, consigliato, PostgreSQL.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DJANGO_DEBUG=1
export DATABASE_URL=postgres://utente:password@localhost:5432/fatturazione   # senza: usa SQLite
python manage.py migrate
python manage.py createsuperuser      # crea il tuo utente
python manage.py runserver
```

Poi apri http://localhost:8000, accedi e compila **Dati azienda**.

## Produzione

Copia `.env.example` in `.env` e compila i valori. Con `DJANGO_DEBUG=0` l'applicazione rifiuta di partire
senza `DJANGO_SECRET_KEY` e `DATABASE_URL`, e attiva HTTPS obbligatorio, cookie sicuri e HSTS.
Prima di andare online esegui `python manage.py check --deploy`.

## Test

```bash
DJANGO_DEBUG=1 python manage.py test
```

I test girano anche su GitHub Actions con PostgreSQL a ogni pull request.

## Da verificare

- Il testo del riferimento normativo per le righe in forfettario è modificabile in **Dati azienda**.
  Lo schema 1.2.4 cita per RF19 un nuovo riferimento (D.Lgs. 117/2026): va aggiornato quando diventerà
  applicabile.
