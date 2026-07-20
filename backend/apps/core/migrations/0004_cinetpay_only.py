from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_payment_settings_alter_gateway_host_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='method',
            field=models.CharField(choices=[('cinetpay', 'CinetPay')], max_length=20),
        ),
        migrations.AlterField(
            model_name='payment',
            name='status',
            field=models.CharField(choices=[('pending', 'En attente'), ('accepted', 'Accepté'), ('refused', 'Refusé'), ('cancelled', 'Annulé'), ('failed', 'Échoué')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='payment',
            name='checkout_url',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='provider_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='payment',
            name='provider_transaction_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='payment_method',
            field=models.CharField(blank=True, choices=[('cinetpay', 'CinetPay')], max_length=20, null=True),
        ),
    ]
