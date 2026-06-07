"""Apply fake historical waves to real ServerHistory data.

Reads the current open ServerHistory rows (real server_key/attributes from the
inventory import) and creates SCD2 changes spread across the period between
--from and today: OS upgrades, CPU doublings, and a small decommission wave.

Designed to run once after the initial backdated import:
    python manage.py import_server_history --clear --date 2026-01-01
    python manage.py seed_history_waves --from 2026-01-01
"""
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import ServerHistory

OS_TO_FAMILY = {
    'RHEL8': 'Linux', 'RHEL9': 'Linux', 'RHEL7': 'Linux', 'RHEL6': 'Linux',
    'Ubuntu 22.04': 'Linux', 'Ubuntu 20.04': 'Linux', 'Ubuntu 18.04': 'Linux',
    'SLES15': 'Linux', 'SLES12': 'Linux', 'Debian 11': 'Linux', 'Debian 10': 'Linux',
    'CentOS 7': 'Linux', 'CentOS 8': 'Linux',
    'Windows 2019': 'Windows', 'Windows 2022': 'Windows',
    'Windows 2016': 'Windows', 'Windows 2012': 'Windows',
}

# Typical OS migration paths
OS_UPGRADES = {
    'RHEL6':        'RHEL8',
    'RHEL7':        'RHEL8',
    'RHEL8':        'RHEL9',
    'CentOS 7':     'RHEL8',
    'CentOS 8':     'RHEL9',
    'Ubuntu 18.04': 'Ubuntu 22.04',
    'Ubuntu 20.04': 'Ubuntu 22.04',
    'Windows 2012': 'Windows 2019',
    'Windows 2016': 'Windows 2022',
    'Windows 2019': 'Windows 2022',
    'SLES12':       'SLES15',
}


def _date_at(start, end, fraction):
    """Return a date at `fraction` of the [start, end] interval."""
    delta = (end - start).days
    return start + timedelta(days=int(delta * fraction))


class Command(BaseCommand):
    help = 'Add fake historical waves to existing ServerHistory rows.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--from', dest='start', default='2026-01-01',
            help='Start of the simulated period (must match the --date used in import).',
        )
        parser.add_argument(
            '--os-pct', type=float, default=12.0,
            help='%% of servers to receive an OS upgrade (default: 12).',
        )
        parser.add_argument(
            '--cpu-pct', type=float, default=8.0,
            help='%% of servers to receive a CPU doubling (default: 8).',
        )
        parser.add_argument(
            '--decomm-pct', type=float, default=2.0,
            help='%% of servers to decommission (default: 2).',
        )
        parser.add_argument(
            '--seed', type=int, default=42,
            help='Random seed for reproducibility.',
        )

    def handle(self, *args, **options):
        random.seed(options['seed'])
        start = date.fromisoformat(options['start'])
        today = date.today()

        if start >= today:
            self.stderr.write('--from must be before today.')
            return

        # ── Load open rows ─────────────────────────────────────────────────
        open_rows = list(
            ServerHistory.objects.filter(valid_to__isnull=True)
            .values('id', 'SERVER_ID', 'APP_NAME_VALUE', 'APP_CRITICALITY',
                    'ENVIRONMENT', 'OSSHORTNAME', 'OSFAMILY', 'REGION', 'SNOW_DATACENTER',
                    'MACHINE_TYPE', 'MANUFACTURER', 'SNOW_STATUS',
                    'CPU', 'RAM')
        )
        if not open_rows:
            self.stderr.write('No open ServerHistory rows found. Run import first.')
            return

        total = len(open_rows)
        self.stdout.write(f'{total:,} open rows loaded. Period: {start} to {today}')

        n_os    = max(1, int(total * options['os_pct']  / 100))
        n_cpu   = max(1, int(total * options['cpu_pct'] / 100))
        n_decomm = max(1, int(total * options['decomm_pct'] / 100))

        # Prefer upgradable OS for the OS wave
        upgradable = [r for r in open_rows if r['OSSHORTNAME'] in OS_UPGRADES]
        non_upgradable = [r for r in open_rows if r['OSSHORTNAME'] not in OS_UPGRADES]
        random.shuffle(upgradable)
        random.shuffle(non_upgradable)

        # Pool for CPU/decomm (avoid overlap with OS targets)
        os_targets  = upgradable[:n_os] + non_upgradable[:max(0, n_os - len(upgradable))]
        os_ids      = {r['id'] for r in os_targets}
        remaining   = [r for r in open_rows if r['id'] not in os_ids]
        random.shuffle(remaining)
        cpu_targets   = remaining[:n_cpu]
        cpu_ids       = {r['id'] for r in cpu_targets}
        decomm_pool   = [r for r in remaining if r['id'] not in cpu_ids]
        decomm_targets = decomm_pool[:n_decomm]

        self.stdout.write(
            f'  OS upgrades: {len(os_targets)}  '
            f'CPU doublings: {len(cpu_targets)}  '
            f'Decomms: {len(decomm_targets)}'
        )

        # ── Build (old_id, new_row_or_None, change_date) triples ──────────
        # Wave 1 ~25%: first OS upgrades
        # Wave 2 ~45%: CPU doublings
        # Wave 3 ~65%: second batch of OS upgrades
        # Wave 4 ~80%: decomms
        wave_dates = {
            'os1':    _date_at(start, today, 0.25),
            'cpu':    _date_at(start, today, 0.45),
            'os2':    _date_at(start, today, 0.65),
            'decomm': _date_at(start, today, 0.80),
        }

        ids_to_close = []   # [(id, close_date)]
        rows_to_insert = []

        split = len(os_targets) // 2

        for i, row in enumerate(os_targets):
            wave_date = wave_dates['os1'] if i < split else wave_dates['os2']
            new_os = OS_UPGRADES.get(row['OSSHORTNAME'], row['OSSHORTNAME'])
            ids_to_close.append((row['id'], wave_date))
            rows_to_insert.append(ServerHistory(
                SERVER_ID=row['SERVER_ID'], APP_NAME_VALUE=row['APP_NAME_VALUE'],
                APP_CRITICALITY=row['APP_CRITICALITY'], ENVIRONMENT=row['ENVIRONMENT'],
                OSSHORTNAME=new_os,
                OSFAMILY=OS_TO_FAMILY.get(new_os) or OS_TO_FAMILY.get(row['OSSHORTNAME']) or row['OSFAMILY'],
                REGION=row['REGION'], SNOW_DATACENTER=row['SNOW_DATACENTER'],
                MACHINE_TYPE=row['MACHINE_TYPE'], MANUFACTURER=row['MANUFACTURER'],
                SNOW_STATUS=row['SNOW_STATUS'],
                CPU=row['CPU'], RAM=row['RAM'],
                valid_from=wave_date, valid_to=None,
            ))

        for row in cpu_targets:
            wave_date = wave_dates['cpu']
            new_cpu = (row['CPU'] or 8) * 2
            ids_to_close.append((row['id'], wave_date))
            rows_to_insert.append(ServerHistory(
                SERVER_ID=row['SERVER_ID'], APP_NAME_VALUE=row['APP_NAME_VALUE'],
                APP_CRITICALITY=row['APP_CRITICALITY'], ENVIRONMENT=row['ENVIRONMENT'],
                OSSHORTNAME=row['OSSHORTNAME'], OSFAMILY=row['OSFAMILY'],
                REGION=row['REGION'], SNOW_DATACENTER=row['SNOW_DATACENTER'],
                MACHINE_TYPE=row['MACHINE_TYPE'], MANUFACTURER=row['MANUFACTURER'],
                SNOW_STATUS=row['SNOW_STATUS'],
                CPU=new_cpu, RAM=row['RAM'],
                valid_from=wave_date, valid_to=None,
            ))

        for row in decomm_targets:
            wave_date = wave_dates['decomm']
            ids_to_close.append((row['id'], wave_date))
            # No new row — server is decommissioned

        # ── Apply ──────────────────────────────────────────────────────────
        with transaction.atomic():
            for old_id, close_date in ids_to_close:
                ServerHistory.objects.filter(id=old_id).update(valid_to=close_date)
            ServerHistory.objects.bulk_create(rows_to_insert, batch_size=2000)

        closed  = len(ids_to_close)
        created = len(rows_to_insert)
        still_open = total - len(decomm_targets)
        self.stdout.write(self.style.SUCCESS(
            f'Done — {closed} rows closed, {created} new open rows inserted. '
            f'{still_open:,} servers active today.'
        ))
