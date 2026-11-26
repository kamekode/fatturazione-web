from django.db import migrations, models

CAMPO = dict(
    help_text="Se il bollo è dovuto, i 2 € vengono aggiunti al totale da pagare.",
    verbose_name="bollo a carico del cliente",
)


class Migration(migrations.Migration):
    dependencies = [
        ("fatture", "0002_fattura_numero_rate_fattura_termini_pagamento_and_more"),
    ]

    operations = [
        # Le fatture già esistenti restano com'erano (bollo non addebitato al cliente).
        migrations.AddField(
            model_name="fattura",
            name="bollo_a_carico_cliente",
            field=models.BooleanField(default=False, **CAMPO),
        ),
        # Le nuove fatture lo addebitano per impostazione predefinita.
        migrations.AlterField(
            model_name="fattura",
            name="bollo_a_carico_cliente",
            field=models.BooleanField(default=True, **CAMPO),
        ),
    ]
