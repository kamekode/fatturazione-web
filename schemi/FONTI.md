# Fonti ufficiali

Tutti i file in `fatturapa/` sono scaricati senza modifiche dal sito ufficiale del Sistema di Interscambio,
pagina [Formato FatturaPA](https://www.fatturapa.gov.it/it/norme-e-regole/documentazione-fattura-elettronica/formato-fatturapa/)
(consultata il 26/11/2026).

| File | Valido | Origine |
|---|---|---|
| `Schema_VFPR12_v1.2.3.xsd` | dal 1 aprile 2025 | https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd |
| `Schema_VFPR12_v1.2.4.xsd` | dall'11 gennaio 2027 | https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.5/Schema_VFPR12_v1.2.4.xsd |
| `Foglio_di_stile_fattura_ordinaria_ver1.2.3.xsl` | dal 1 aprile 2025 | https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.4/Foglio_di_stile_fattura_ordinaria_ver1.2.3.xsl |
| `Foglio_di_stile_fattura_ordinaria_ver1.2.4.xsl` | dall'11 gennaio 2027 | https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.5/Foglio_di_stile_fattura_ordinaria_ver1.2.4.xsl |
| `IT01234567890_FPR01.xml`, `IT01234567890_FPR02.xml` | esempi versione 1.2 | https://www.fatturapa.gov.it/it/lafatturapa/esempi/ |

Note:

- Tra 1.2.3 e 1.2.4 l'unica differenza strutturale è il nuovo regime fiscale `RF21`; il resto riguarda le
  descrizioni dei riferimenti normativi (nuovo D.Lgs. 10/2026). L'applicazione valida ogni fattura su entrambi.
- Gli esempi ufficiali sono ancora quelli della versione 1.2. `FPR01` è valido sugli schemi attuali,
  `FPR02` no (contiene `ContattiTrasmittente` in una posizione non più accettata), quindi i test usano solo `FPR01`.
- Specifiche tecniche del formato 1.5: https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.5/Specifiche_tecniche_del_formato_FatturaPA_V1.5.pdf

## Regole del canale PEC

Dal documento ufficiale "Allegato A - Specifiche tecniche vers 1.9.1" (Agenzia delle Entrate, utilizzabile dal
15 maggio 2026): https://www.agenziaentrate.gov.it/portale/documents/d/guest/allegato-a-specifiche-tecniche-vers-1-9-1

- primo invio a `sdi01@pec.fatturapa.it`, poi l'indirizzo comunicato dallo SdI con il primo messaggio di risposta;
- file fattura come allegato del messaggio PEC (limite 30 MB);
- nomenclatura di ricevute e notifiche: `<nome file fattura>_<RC|NS|MC|MT>_<progressivo>.xml`;
- fatture firmate accettate in CAdES (`.xml.p7m`) o XAdES (`.xml`).

Parametri della casella PEC Aruba: https://guide.aruba.it/pec/configurazione-programmi-di-posta/client-posta-e-dispositivi-mobili

## Regime forfetario (stima di imposte e acconti)

- Agenzia delle Entrate, "Regime forfetario - Che cos'è": coefficiente di redditività sui ricavi, deduzione dei
  contributi previdenziali obbligatori, imposta sostitutiva del 15% (5% per i primi cinque anni con i requisiti),
  soglie di 85.000 euro (accesso) e 100.000 euro (uscita nello stesso anno).
  https://www.agenziaentrate.gov.it/portale/regime-forfetario-le-regole-2020-/infogen-regime-forfetario-le-regole-2020-
- Istruzioni Redditi PF, fascicolo 3, quadro LM: tabella dei coefficienti (allegato 2 alla L. 145/2018),
  "Altre attività economiche" 67% (comprende i codici ATECO 33 e 95).
  https://www.agenziaentrate.gov.it/portale/documents/20143/8836009/PF3_istruzioni_2025_agg+12+05+2025.pdf
- Istruzioni Redditi 2026: acconto non dovuto fino a 51,65 euro, unica soluzione entro il 30 novembre sotto
  257,52 euro, altrimenti due rate (giugno e novembre); scadenze di sabato o festive al primo giorno feriale.
  https://www.agenziaentrate.gov.it/portale/documents/d/guest/pf2_istruzioni_2026
- Risoluzione 93/E del 12 novembre 2019: per i soggetti ISA, compresi i forfetari, le due rate di acconto
  dell'imposta sostitutiva sono del 50% ciascuna.
  https://www.agenziaentrate.gov.it/portale/documents/20143/2139920/Risoluzione+n.+93+del+12+novembre+2019.pdf

I parametri dei contributi INPS (minimale, contributi fissi, aliquote) cambiano ogni anno e non sono inclusi:
si inseriscono nel profilo fiscale dalla circolare INPS dell'anno.
