"""Check restored domain counts and real dashboard/report portability."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'dine_iq'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dine_iq.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from apps.restaurants.reports import REPORTS
from apps.restaurants.management.commands.import_clean_dataset import TABLES

user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
if not user:
    raise SystemExit('The restored database has no active superuser.')
for name, model, _ in TABLES:
    print(f'{name}: {model.objects.count():,}')
client = Client(HTTP_HOST='127.0.0.1')
client.force_login(user)
paths = ['/dashboard/', '/dashboard/menu/', '/dashboard/customers/', '/dashboard/wastage/',
         '/dashboard/forecast/', '/dashboard/dual/', '/dashboard/search/', '/reports/',
         '/locations/', '/locations/recommendations/', '/locations/scenarios/']
paths += [f'/reports/{slug}/download/' for slug in REPORTS]
try:
    for path in paths:
        response = client.get(path)
        if response.status_code != 200:
            raise SystemExit(f'FAILED {path}: HTTP {response.status_code}')
        print(f'PASS {path}')
finally:
    client.logout()
print(f'Passed {len(paths)} populated application/report requests.')
