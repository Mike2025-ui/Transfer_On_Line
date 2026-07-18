import uuid
from decimal import Decimal
from django.db import models

class Device(models.Model):
    uid = models.CharField(max_length=100, unique=True)
    primary_phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.uid} - {self.primary_phone}"

class Service(models.Model):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=20)

    def __str__(self):
        return self.name

class Operator(models.Model):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=10)

    def __str__(self):
        return self.name

class Gateway(models.Model):
    name = models.CharField(max_length=100)
    host = models.CharField(max_length=255, blank=True, null=True)
    port = models.IntegerField(default=8080)
    is_active = models.BooleanField(default=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='offline')

    def __str__(self):
        return self.name

class Payment(models.Model):
    METHOD_CHOICES = [
        ('orange_money', 'Orange Money'),
        ('mtn_momo', 'MTN MoMo'),
        ('wave', 'Wave'),
    ]
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.method} - {self.reference}"

class Transaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('success', 'Réussi'),
        ('failed', 'Échoué'),
        ('cancelled', 'Annulé'),
    ]

    reference = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    gateway = models.ForeignKey(Gateway, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    phone_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    payment_method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES, blank=True, null=True)
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.commission:
            self.commission = self.amount * Decimal('0.01')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.amount} FCFA"

class Refund(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('completed', 'Terminé'),
    ]
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Remboursement pour {self.transaction.reference}"

class Settings(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.key} = {self.value}"

class AdminProfile(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='admin_profile')
    phone = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.user.username

class AuditLog(models.Model):
    admin = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.admin} - {self.action} - {self.timestamp}"

