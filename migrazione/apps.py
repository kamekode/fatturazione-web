from django.apps import AppConfig


class MigrazioneConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "migrazione"
    verbose_name = "Migrazione da altri programmi"
