"""Codifiche dello schema FatturaPA (Fattura Ordinaria 1.2.3 / 1.2.4)."""

from django.db import models


class TipoDocumento(models.TextChoices):
    FATTURA = "TD01", "TD01 - Fattura"
    ACCONTO = "TD02", "TD02 - Acconto/anticipo su fattura"
    NOTA_CREDITO = "TD04", "TD04 - Nota di credito"
    NOTA_DEBITO = "TD05", "TD05 - Nota di debito"
    PARCELLA = "TD06", "TD06 - Parcella"
    DIFFERITA = "TD24", "TD24 - Fattura differita (beni con DDT)"
    DIFFERITA_B = "TD25", "TD25 - Fattura differita (triangolazione interna)"


class Natura(models.TextChoices):
    N1 = "N1", "N1 - Escluse ex art. 15"
    N2_1 = "N2.1", "N2.1 - Non soggette (artt. da 7 a 7-septies)"
    N2_2 = "N2.2", "N2.2 - Non soggette, altri casi (forfettario)"
    N3_1 = "N3.1", "N3.1 - Non imponibili, esportazioni"
    N3_2 = "N3.2", "N3.2 - Non imponibili, cessioni intracomunitarie"
    N4 = "N4", "N4 - Esenti"
    N6_9 = "N6.9", "N6.9 - Inversione contabile, altri casi"
    N7 = "N7", "N7 - IVA assolta in altro stato UE"


class ModalitaPagamento(models.TextChoices):
    CONTANTI = "MP01", "MP01 - Contanti"
    ASSEGNO = "MP02", "MP02 - Assegno"
    BONIFICO = "MP05", "MP05 - Bonifico"
    RIBA = "MP12", "MP12 - RIBA"
    PAGOPA = "MP23", "MP23 - PagoPA"
    CARTA = "MP08", "MP08 - Carta di pagamento"


class CondizioniPagamento(models.TextChoices):
    RATE = "TP01", "TP01 - A rate"
    COMPLETO = "TP02", "TP02 - Pagamento completo"
    ANTICIPO = "TP03", "TP03 - Anticipo"
