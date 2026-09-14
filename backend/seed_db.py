#!/usr/bin/env python
"""
Standalone seed script for Transfer On Line PostgreSQL database.
Usage:
  python seed_db.py
or via docker:
  docker compose --env-file backend/.env exec backend python seed_db.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')
django.setup()

from django.core.management import call_command

if __name__ == '__main__':
    call_command('seed_production_data')
