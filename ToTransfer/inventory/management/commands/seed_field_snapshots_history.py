import datetime
import random

from django.core.management.base import BaseCommand

from inventory.models import FieldSnapshot


class Command(BaseCommand):
    help = 'Seed fake historical FieldSnapshot data based on today\'s snapshots (dev only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of past days to generate (default: 30)',
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=42,
            help='Random seed for reproducibility',
        )

    def handle(self, *args, **options):
        random.seed(options['seed'])
        today = datetime.date.today()
        n_days = options['days']

        today_snapshots = list(FieldSnapshot.objects.filter(date=today))
        if not today_snapshots:
            self.stderr.write("No snapshots found for today. Run snapshot_field_counts first.")
            return

        field_names = list({s.field_name for s in today_snapshots})
        self.stdout.write(f"Found {len(today_snapshots)} snapshot(s) for today across {len(field_names)} field(s)")
        self.stdout.write(f"Generating {n_days} past day(s)...")

        to_create = []
        skipped = 0

        for day_offset in range(1, n_days + 1):
            target_date = today - datetime.timedelta(days=day_offset)

            if FieldSnapshot.objects.filter(date=target_date).exists():
                skipped += 1
                continue

            for snap in today_snapshots:
                # Apply a small cumulative drift backwards in time.
                # Each day back: ±0–3% variation, slightly biased downward
                # (older = slightly fewer servers on average).
                drift = 1.0 - (day_offset * random.uniform(-0.005, 0.025))
                noise = random.uniform(-0.01, 0.01)
                factor = max(0.0, drift + noise)
                count = max(0, round(snap.count * factor))

                to_create.append(FieldSnapshot(
                    date=target_date,
                    field_name=snap.field_name,
                    field_value=snap.field_value,
                    count=count,
                ))

        if skipped:
            self.stdout.write(f"  Skipped {skipped} day(s) that already have data")

        FieldSnapshot.objects.bulk_create(to_create)
        self.stdout.write(self.style.SUCCESS(
            f"Done — {len(to_create)} row(s) inserted across {n_days - skipped} day(s)"
        ))
