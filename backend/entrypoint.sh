#!/bin/bash
# Initialization script for Transfer On Line Docker deployment
# Runs migrations, creates superuser, seeds initial data, and collects static files

set -e

echo "=========================================="
echo "Transfer On Line - Docker Initialization"
echo "=========================================="

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
while ! nc -z postgres 5432; do
  sleep 1
done
echo "✅ PostgreSQL is ready"

# Run migrations
echo "⏳ Running database migrations..."
python manage.py migrate --noinput
echo "✅ Migrations completed"

# Collect static files
echo "⏳ Collecting static files..."
python manage.py collectstatic --noinput --clear
echo "✅ Static files collected"

# Seed initial data (services, operators, etc.)
echo "⏳ Seeding initial data..."
python manage.py shell << EOF
from apps.core.models import Operator, Service

# Create canonical operators
operators_data = [
    {
        'name': 'MTN Côte d\'Ivoire',
        'code': 'mtn',
        'country': 'CI',
        'mcc': '612',
        'mnc': '01',
    },
    {
        'name': 'Orange Côte d\'Ivoire',
        'code': 'orange',
        'country': 'CI',
        'mcc': '612',
        'mnc': '03',
    },
    {
        'name': 'Wave Côte d\'Ivoire',
        'code': 'wave',
        'country': 'CI',
        'mcc': '612',
        'mnc': '05',
    },
    {
        'name': 'Moov Côte d\'Ivoire',
        'code': 'moov',
        'country': 'CI',
        'mcc': '612',
        'mnc': '02',
    },
]

for op_data in operators_data:
    Operator.objects.get_or_create(code=op_data['code'], defaults=op_data)

# Create canonical services
services_data = [
    {
        'name': 'Souscription Appelle',
        'code': 'subscription_voice',
        'description': 'Abonnement aux services d\'appels',
    },
    {
        'name': 'Souscription SMS',
        'code': 'subscription_sms',
        'description': 'Abonnement aux services SMS',
    },
    {
        'name': 'Souscription Internet',
        'code': 'subscription_internet',
        'description': 'Abonnement aux services Internet',
    },
    {
        'name': 'Transfert d\'unité',
        'code': 'transfert_unite',
        'description': 'Transfert de crédit vers d\'autres numéros',
    },
]

for svc_data in services_data:
    Service.objects.get_or_create(code=svc_data['code'], defaults={**svc_data, 'is_active': True})

print("✅ Initial data seeded successfully")
EOF

# Create superuser if it doesn't exist
echo "⏳ Checking superuser..."
python manage.py shell << EOF
from django.contrib.auth.models import User
import os

username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@transfer-on-line.local')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'changeme')

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f"✅ Superuser '{username}' created")
else:
    print(f"✅ Superuser '{username}' already exists")
EOF

echo ""
echo "=========================================="
echo "✅ Initialization completed successfully!"
echo "=========================================="
echo ""
echo "Application is running on http://localhost:8000"
echo "Admin panel available at http://localhost:8000/admin"
echo ""
