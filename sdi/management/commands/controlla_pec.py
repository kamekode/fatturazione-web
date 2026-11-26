from django.core.management.base import BaseCommand, CommandError

from sdi.pec import ErrorePEC, leggi_casella


class Command(BaseCommand):
    help = "Legge la casella PEC: notifiche dello SdI e fatture ricevute. Adatto a un'attività pianificata."

    def handle(self, *args, **options):
        try:
            esito = leggi_casella()
        except ErrorePEC as errore:
            raise CommandError(str(errore)) from errore
        self.stdout.write(
            f"{esito.messaggi} messaggi, {len(esito.notifiche)} notifiche, {len(esito.fatture_ricevute)} fatture ricevute"
        )
        for errore in esito.errori:
            self.stderr.write(errore)
