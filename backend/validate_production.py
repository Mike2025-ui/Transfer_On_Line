#!/usr/bin/env python
"""
Production Validation Script
Runs Django check --deploy and outputs results to console and file.
"""
import os
import sys
import subprocess
from pathlib import Path

os.chdir(Path(__file__).parent)

print("=" * 80)
print("PRODUCTION VALIDATION - Transfer On Line")
print("=" * 80)
print()

# Run check --deploy
print("Running: python manage.py check --deploy")
print("-" * 80)

result = subprocess.run(
    [sys.executable, 'manage.py', 'check', '--deploy'],
    capture_output=False,
    text=True
)

print()
print("=" * 80)
if result.returncode == 0:
    print("✅ ALL CHECKS PASSED - PRODUCTION READY")
else:
    print(f"⚠️  CHECKS FAILED - Exit Code: {result.returncode}")
print("=" * 80)

sys.exit(result.returncode)
