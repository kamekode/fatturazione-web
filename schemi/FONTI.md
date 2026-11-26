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
