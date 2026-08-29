from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0019_alter_payment_method_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='method',
            field=models.CharField(
                choices=[
                    ('auto', 'Automatique (relais)'),
                    ('cinetpay', 'CinetPay'),
                    ('jeko', 'Jèko'),
                    ('feexpay', 'FeexPay'),
                    ('geniuspay', 'GeniusPay'),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('auto', 'Automatique (relais)'),
                    ('cinetpay', 'CinetPay'),
                    ('jeko', 'Jèko'),
                    ('feexpay', 'FeexPay'),
                    ('geniuspay', 'GeniusPay'),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
