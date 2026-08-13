from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from discrepancies.models import DailyPamelaDBSummary

# Real PAMELA export sample (name/techfamily/area/UniqueHostCount columns from the SQL Server
# dump), transcribed as-is — raw techfamily labels (Hypervisor, Linux Server, Unix Server,
# Appliance, IV2-MP-STG - * variants, blank) are stored verbatim, not pre-simplified. Bucketing
# (Linux/Windows/Other) happens at read time via breakdown_groups.json "pamela.techfamily_buckets"
# so the mapping can be tuned without touching this data. Blank area/techfamily cells in the
# source dump are stored as '' (not a sentinel string) — they're real, distinct combinations,
# not roll-up totals (AllServerTotal, the flat 92230 grand total, is the only real roll-up and
# isn't stored at all — not used).
# report_type='allserver' is PAMELA's own population count per (area, techfamily) — used as the
# denominator for the missing_* rows, instead of borrowing inventory's OS-family population.
SAMPLE_DATA = {
    'allserver': {
        ('', ''): 8, ('AMER', ''): 6, ('APAC', ''): 80, ('EMEA', ''): 125, ('ISPL', ''): 16, ('MEAA', ''): 19,
        ('APAC', 'Appliance'): 1, ('EMEA', 'Appliance'): 3,
        ('', 'Hypervisor'): 3, ('AMER', 'Hypervisor'): 586, ('APAC', 'Hypervisor'): 790, ('EMEA', 'Hypervisor'): 2225, ('ISPL', 'Hypervisor'): 41, ('MEAA', 'Hypervisor'): 41,
        ('EMEA', 'IV2-MP-STG - Linux Server'): 175, ('EMEA', 'IV2-MP-STG - Windows Server'): 43,
        ('', 'Linux Server'): 5, ('AMER', 'Linux Server'): 8456, ('APAC', 'Linux Server'): 9071, ('EMEA', 'Linux Server'): 41331, ('ISPL', 'Linux Server'): 334, ('MEAA', 'Linux Server'): 68,
        ('EMEA', 'Linux Workstation'): 1,
        ('APAC', 'Unix Server'): 6, ('EMEA', 'Unix Server'): 43, ('ISPL', 'Unix Server'): 1, ('MEAA', 'Unix Server'): 3,
        ('AMER', 'Windows Server'): 4562, ('APAC', 'Windows Server'): 4275, ('EMEA', 'Windows Server'): 19465, ('ISPL', 'Windows Server'): 294, ('MEAA', 'Windows Server'): 153,
    },
    'missing_AD': {
        ('', ''): 3, ('AMER', ''): 2, ('APAC', ''): 35, ('EMEA', ''): 98, ('ISPL', ''): 12, ('MEAA', ''): 3,
        ('APAC', 'Appliance'): 1, ('EMEA', 'Appliance'): 3,
        ('', 'Hypervisor'): 3, ('AMER', 'Hypervisor'): 586, ('APAC', 'Hypervisor'): 729, ('EMEA', 'Hypervisor'): 1999, ('ISPL', 'Hypervisor'): 41, ('MEAA', 'Hypervisor'): 3,
        ('EMEA', 'IV2-MP-STG - Linux Server'): 14, ('EMEA', 'IV2-MP-STG - Windows Server'): 7,
        ('', 'Linux Server'): 5, ('AMER', 'Linux Server'): 346, ('APAC', 'Linux Server'): 565, ('EMEA', 'Linux Server'): 2508, ('ISPL', 'Linux Server'): 21,
        ('EMEA', 'Linux Workstation'): 1,
        ('APAC', 'Unix Server'): 2, ('ISPL', 'Unix Server'): 1, ('MEAA', 'Unix Server'): 1,
        ('AMER', 'Windows Server'): 635, ('APAC', 'Windows Server'): 74, ('EMEA', 'Windows Server'): 70, ('MEAA', 'Windows Server'): 2,
    },
    'missing_ADDM': {
        ('', ''): 6, ('AMER', ''): 1, ('APAC', ''): 67, ('EMEA', ''): 110, ('ISPL', ''): 13, ('MEAA', ''): 14,
        ('APAC', 'Appliance'): 1, ('EMEA', 'Appliance'): 2,
        ('', 'Hypervisor'): 1, ('APAC', 'Hypervisor'): 5, ('EMEA', 'Hypervisor'): 58,
        ('EMEA', 'IV2-MP-STG - Linux Server'): 17, ('EMEA', 'IV2-MP-STG - Windows Server'): 13,
        ('', 'Linux Server'): 5, ('AMER', 'Linux Server'): 25, ('APAC', 'Linux Server'): 37, ('EMEA', 'Linux Server'): 178, ('ISPL', 'Linux Server'): 2,
        ('APAC', 'Unix Server'): 2, ('EMEA', 'Unix Server'): 1,
        ('AMER', 'Windows Server'): 18, ('APAC', 'Windows Server'): 91, ('EMEA', 'Windows Server'): 127, ('ISPL', 'Windows Server'): 2, ('MEAA', 'Windows Server'): 9,
    },
    'missing_CA': {
        ('', ''): 8, ('AMER', ''): 2, ('APAC', ''): 61, ('EMEA', ''): 59, ('ISPL', ''): 16, ('MEAA', ''): 15,
        ('EMEA', 'Appliance'): 1,
        ('', 'Hypervisor'): 1, ('AMER', 'Hypervisor'): 102, ('APAC', 'Hypervisor'): 187, ('EMEA', 'Hypervisor'): 389, ('ISPL', 'Hypervisor'): 16, ('MEAA', 'Hypervisor'): 10,
        ('', 'Linux Server'): 5, ('AMER', 'Linux Server'): 37, ('APAC', 'Linux Server'): 11, ('EMEA', 'Linux server'): 37, ('ISPL', 'Linux Server'): 13,
        ('APAC', 'Unix Server'): 2, ('EMEA', 'Unix Server'): 2, ('MEAA', 'Unix Server'): 3,
        ('AMER', 'Windows Server'): 2, ('APAC', 'Windows Server'): 41, ('EMEA', 'Windows Server'): 75, ('ISPL', 'Windows Server'): 9, ('MEAA', 'Windows Server'): 3,
    },
    'missing_EPO': {
        ('', ''): 7, ('AMER', ''): 1, ('APAC', ''): 72, ('EMEA', ''): 103, ('ISPL', ''): 16, ('MEAA', ''): 9,
        ('APAC', 'Appliance'): 1, ('EMEA', 'Appliance'): 2,
        ('', 'Hypervisor'): 3, ('AMER', 'Hypervisor'): 31, ('APAC', 'Hypervisor'): 770, ('EMEA', 'Hypervisor'): 1929, ('ISPL', 'Hypervisor'): 41, ('MEAA', 'Hypervisor'): 3,
        ('EMEA', 'IV2-MP-STG - Linux Server'): 11, ('EMEA', 'IV2-MP-STG - Windows Server'): 8,
        ('', 'Linux Server'): 5, ('AMER', 'Linux Server'): 44, ('APAC', 'Linux Server'): 95, ('EMEA', 'Linux Server'): 784, ('ISPL', 'Linux Server'): 1,
        ('APAC', 'Unix Server'): 6, ('EMEA', 'Unix Server'): 1, ('ISPL', 'Unix Server'): 1, ('MEAA', 'Unix Server'): 1,
        ('AMER', 'Windows Server'): 6, ('APAC', 'Windows Server'): 81, ('EMEA', 'Windows Server'): 96, ('ISPL', 'Windows Server'): 3, ('MEAA', 'Windows Server'): 2,
    },
    'missing_LA': {
        ('EMEA', 'Appliance'): 1,
        ('AMER', 'Hypervisor'): 4, ('APAC', 'Hypervisor'): 9, ('EMEA', 'Hypervisor'): 19,
        ('EMEA', 'IV2-MP-STG - Linux Server'): 3,
        ('AMER', 'Linux Server'): 2, ('APAC', 'Linux Server'): 1, ('EMEA', 'Linux Server'): 130,
    },
    'missing_SA': {
        ('EMEA', 'IV2-MP-STG - Linux Server'): 4,
        ('AMER', 'Linux Server'): 46, ('APAC', 'Linux Server'): 13, ('EMEA', 'Linux Server'): 56, ('ISPL', 'Linux Server'): 1,
    },
}


class Command(BaseCommand):
    help = 'Reset DailyPamelaDBSummary and reseed it with a real PAMELA CSV export sample (dev substitute for the ODBC/CSV import)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', dest='snapshot_date', default=None,
            help='Snapshot date as YYYY-MM-DD (default: today)',
        )
        parser.add_argument(
            '--days', dest='days', type=int, default=1,
            help='Seed this many consecutive days ending at --date (default: 1). The '
                 'population is repeated as-is for every day (PAMELA\'s total fleet size '
                 'does not swing day to day) — only ServerDiscrepancyPamela varies day to '
                 'day, see seed_pamela_server_discrepancies --days.',
        )

    def handle(self, *args, **options):
        end_date = (
            date.fromisoformat(options['snapshot_date'])
            if options['snapshot_date'] else date.today()
        )
        n_days = max(1, options['days'])

        total_created = 0
        with transaction.atomic():
            for offset in range(n_days):
                snapshot_date = end_date - timedelta(days=n_days - 1 - offset)

                # Only wipe THIS date's rows — keeps the command safe to re-run for several
                # snapshot dates in a row without nuking previously-seeded dates every time.
                DailyPamelaDBSummary.objects.filter(snapshot_date=snapshot_date).delete()

                rows = [
                    DailyPamelaDBSummary(
                        report_type=report_type, techfamily=techfamily, area=area,
                        total_count=total_count, snapshot_date=snapshot_date,
                    )
                    for report_type, entries in SAMPLE_DATA.items()
                    for (area, techfamily), total_count in entries.items()
                ]
                DailyPamelaDBSummary.objects.bulk_create(rows)
                total_created += len(rows)

        self.stdout.write(self.style.SUCCESS(
            f"DailyPamelaDBSummary reseeded for {n_days} day(s) ending {end_date}: "
            f"{total_created} rows created"
        ))
