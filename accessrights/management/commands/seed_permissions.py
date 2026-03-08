"""
Management command to seed Permission rows from permissions.json.

Usage:
    python manage.py seed_permissions

Run this after migrations, or whenever you update permissions.json.
It creates missing permissions but never deletes existing ones.
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from accessrights.models import Permission


class Command(BaseCommand):
    help = 'Seed Permission table from permissions.json'

    def handle(self, *args, **options):
        json_path = os.path.join(
            settings.BASE_DIR,
            'accessrights', 'static', 'accessrights', 'permissions.json',
        )

        with open(json_path) as f:
            config = json.load(f)

        created = 0
        existing = 0

        for app in config.get('apps', []):
            app_key = app['key']
            for action in app.get('permissions', []):
                codename = f"{app_key}.{action}"
                label = action.capitalize()

                _, was_created = Permission.objects.get_or_create(
                    codename=codename,
                    defaults={
                        'app': app_key,
                        'action': action,
                        'label': label,
                    },
                )

                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  Created: {codename}"))
                else:
                    existing += 1

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(f"Done — {created} created, {existing} already existed")
        )
