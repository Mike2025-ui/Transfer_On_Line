from django.db import models


class EmailVerificationCode(models.Model):
	email = models.EmailField()
	code_hash = models.CharField(max_length=128)
	expires_at = models.DateTimeField()
	attempts = models.PositiveSmallIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		indexes = [models.Index(fields=['email', 'created_at'])]
