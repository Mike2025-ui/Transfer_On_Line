from django.db import migrations, models


class Migration(migrations.Migration):
    """Ikoddi migration: PhoneOtp no longer holds a locally-generated
    hashed code (code_hash) or a locally-tracked expiry (expires_at) -
    Ikoddi's OTP As A Service now owns code generation, delivery and
    expiry. What Django keeps instead is the opaque `verification_key`
    Ikoddi returns when the code is sent (see
    apps.accounts.services.ikoddi_service)."""

    dependencies = [
        ('accounts', '0004_phoneotp_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='phoneotp',
            name='code_hash',
        ),
        migrations.RemoveField(
            model_name='phoneotp',
            name='expires_at',
        ),
        migrations.AddField(
            model_name='phoneotp',
            name='verification_key',
            field=models.TextField(default=''),
            preserve_default=False,
        ),
    ]
