"""Seed server_history with realistic fake data from 2026-01-01 to today.

Creates ~700 initial (server, app) pairs and applies waves of changes to
simulate a 6-month history: OS upgrades, CPU changes, decomms, new arrivals.

PostgreSQL only.
"""
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from inventory.models import ServerHistory

# ── Reference data ────────────────────────────────────────────────────────────

REGIONS = ['EMEA', 'AMER', 'APAC', 'LATAM']
REGION_W = [0.45, 0.30, 0.20, 0.05]

ENVS = ['PROD', 'DEV', 'UAT', 'STAGING']
ENV_W = [0.35, 0.30, 0.20, 0.15]

DC_BY_REGION = {
    'EMEA':  ['PARIS-DC1', 'PARIS-DC2', 'LONDON-DC1', 'FRANKFURT-DC1', 'ZURICH-DC1'],
    'AMER':  ['NYC-DC1', 'CHICAGO-DC1', 'SAN-JOSE-DC1', 'TORONTO-DC1'],
    'APAC':  ['SINGAPORE-DC1', 'TOKYO-DC1', 'SYDNEY-DC1', 'HONG-KONG-DC1'],
    'LATAM': ['SAO-PAULO-DC1', 'MEXICO-DC1'],
}

OS_POOL = [
    ('RHEL8',         0.28),
    ('RHEL9',         0.10),
    ('Windows 2019',  0.22),
    ('Windows 2022',  0.15),
    ('Ubuntu 22.04',  0.14),
    ('SLES15',        0.06),
    ('Ubuntu 20.04',  0.05),
]
OS_CHOICES, OS_WEIGHTS = zip(*OS_POOL)

OS_TO_FAMILY = {
    'RHEL8':        'Linux',
    'RHEL9':        'Linux',
    'Ubuntu 22.04': 'Linux',
    'Ubuntu 20.04': 'Linux',
    'SLES15':       'Linux',
    'Windows 2019': 'Windows',
    'Windows 2022': 'Windows',
}

APPS = [
    'TRADING', 'RISK-MGT', 'COMPLIANCE', 'REPORTING',
    'MIDDLEWARE', 'AUTH-SVC', 'MONITORING', 'BACKUP',
    'FINANCE', 'INFRA-BASE', 'DATA-LAKE', 'ANALYTICS',
    'PAYMENTS', 'FX-ENGINE', 'CLEARING',
]

CRITS = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
CRIT_W = [0.15, 0.30, 0.35, 0.20]

MANUFACTURERS = ['Dell', 'HP', 'Cisco', 'IBM', 'Lenovo']
SERVER_TYPES   = ['VM', 'VM', 'VM', 'PHYSICAL', 'CONTAINER']
CPU_CHOICES    = [4, 8, 8, 16, 16, 32, 64]
RAM_CHOICES    = [8, 16, 16, 32, 32, 64, 128, 256]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wc(population, weights):
    return random.choices(population, weights=weights, k=1)[0]


def _make_server(idx):
    region = _wc(REGIONS, REGION_W)
    return {
        'SERVER_ID':       f'SRV-{idx:05d}',
        'ENVIRONMENT':     _wc(ENVS, ENV_W),
        'OSSHORTNAME':     (os_val := _wc(OS_CHOICES, OS_WEIGHTS)),
        'OSFAMILY':        OS_TO_FAMILY.get(os_val, 'Other'),
        'REGION':          region,
        'SNOW_DATACENTER': random.choice(DC_BY_REGION[region]),
        'MACHINE_TYPE':    random.choice(SERVER_TYPES),
        'MANUFACTURER':    random.choice(MANUFACTURERS),
        'SNOW_STATUS':     'Operational',
        'CPU':             random.choice(CPU_CHOICES),
        'RAM':             random.choice(RAM_CHOICES),
    }


def _make_app_rows(server_dict, app_pool):
    """Return list of (app, criticality) pairs for this server (1 or 2 apps)."""
    n_apps = 2 if random.random() < 0.12 else 1
    apps = random.sample(app_pool, min(n_apps, len(app_pool)))
    return [(app, _wc(CRITS, CRIT_W)) for app in apps]


# ── Core simulation ───────────────────────────────────────────────────────────

class ServerState:
    """Tracks one (server_key, app) pair through time."""

    def __init__(self, server_key, app, criticality, attrs, valid_from):
        self.server_key  = server_key
        self.app         = app
        self.criticality = criticality
        # strip key fields that are stored separately
        self.attrs       = {k: v for k, v in attrs.items() if k not in ('SERVER_ID', 'APP_NAME_VALUE', 'APP_CRITICALITY')}
        self.valid_from  = valid_from
        self.valid_to    = None  # None = still open

    def close(self, close_date):
        self.valid_to = close_date

    def change(self, new_attrs, change_date):
        """Close this state and return a new ServerState inheriting the change."""
        self.close(change_date)
        merged = {**self.attrs, **new_attrs}
        return ServerState(
            self.server_key, self.app, self.criticality,
            merged, change_date,
        )

    def to_orm(self):
        return ServerHistory(
            SERVER_ID=self.server_key,
            APP_NAME_VALUE=self.app,
            APP_CRITICALITY=self.criticality,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
            **self.attrs,
        )


class Command(BaseCommand):
    help = 'Seed server_history with fake data from 2026-01-01 to today (PostgreSQL only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--servers', type=int, default=600,
            help='Number of initial servers (default: 600).',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete all existing ServerHistory rows before seeding.',
        )

    def handle(self, *args, **options):
        random.seed(42)
        start_date = date(2026, 1, 1)
        today = date.today()
        n_servers = options['servers']

        if options['clear']:
            deleted, _ = ServerHistory.objects.all().delete()
            self.stdout.write(f'Cleared {deleted} existing rows.')

        self.stdout.write(f'Generating {n_servers} servers from {start_date} to {today}…')

        # ── 1. Initial state (2026-01-01) ──────────────────────────────────
        # states: {(server_key, app): ServerState} — only open (current) states
        states: dict[tuple, ServerState] = {}
        # all_states: every state (open + closed) to be bulk-inserted
        all_states: list[ServerState] = []

        app_pool = list(APPS)
        for idx in range(1, n_servers + 1):
            machine = _make_server(idx)
            for app, crit in _make_app_rows(machine, app_pool):
                s = ServerState(
                    machine['server_key'], app, crit, machine, start_date
                )
                states[(machine['server_key'], app)] = s

        self.stdout.write(f'  Initial (server, app) pairs: {len(states):,}')

        # ── 2. Event waves ─────────────────────────────────────────────────
        # Each event is (date, type, args)
        # Types: 'new', 'os_upgrade', 'cpu_upgrade', 'decomm'
        events = self._build_events(states, n_servers, start_date, today)
        self.stdout.write(f'  Events to apply: {len(events):,}')

        next_idx = n_servers + 1
        for ev_date, ev_type, ev_args in sorted(events, key=lambda e: e[0]):
            if ev_type == 'new':
                machine = _make_server(next_idx)
                next_idx += 1
                for app, crit in _make_app_rows(machine, app_pool):
                    s = ServerState(
                        machine['server_key'], app, crit, machine, ev_date
                    )
                    states[(machine['server_key'], app)] = s

            elif ev_type == 'os_upgrade':
                key, new_os = ev_args
                if key in states and states[key].valid_to is None:
                    old = states.pop(key)
                    all_states.append(old)
                    new_s = old.change(
                        {'OSSHORTNAME': new_os, 'OSFAMILY': OS_TO_FAMILY.get(new_os, 'Other')},
                        ev_date,
                    )
                    states[key] = new_s

            elif ev_type == 'cpu_upgrade':
                key, multiplier = ev_args
                if key in states and states[key].valid_to is None:
                    old = states.pop(key)
                    all_states.append(old)
                    new_cpu = (old.attrs.get('CPU') or 8) * multiplier
                    new_s = old.change({'CPU': new_cpu}, ev_date)
                    states[key] = new_s

            elif ev_type == 'decomm':
                key = ev_args
                if key in states and states[key].valid_to is None:
                    old = states.pop(key)
                    old.close(ev_date)
                    all_states.append(old)

        # Collect all still-open states
        all_states.extend(states.values())

        # ── 3. Bulk insert ─────────────────────────────────────────────────
        objs = [s.to_orm() for s in all_states]
        self.stdout.write(f'  Inserting {len(objs):,} rows…')
        ServerHistory.objects.bulk_create(objs, batch_size=2000)

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(objs):,} rows inserted '
            f'({len(states):,} open, {len(all_states) - len(states):,} closed).'
        ))

    def _build_events(self, initial_states, n_servers, start_date, today):
        """Build a list of (date, type, args) events spanning start_date → today."""
        events = []
        open_keys = list(initial_states.keys())
        rhel8_keys = [k for k, s in initial_states.items() if s.attrs.get('OSSHORTNAME') == 'RHEL8']

        # Wave definitions: (offset_days, n_new, n_os, n_cpu, n_decomm)
        waves = [
            (14,  25,  5,   0,  3),   # Jan 15
            (31,  20,  8,   0,  5),   # Feb 1
            (50,   0,  0,  12,  4),   # Feb 20 — CPU wave
            (59,  15,  0,   0,  6),   # Mar 1
            (75,   0,  0,  10,  3),   # Mar 16 — CPU wave
            (90,  15, 30,   0,  5),   # Apr 1  — big RHEL8→RHEL9 migration
            (105,  0,  0,   8,  4),   # Apr 16 — CPU wave
            (120, 10,  5,   0,  3),   # May 1
            (135,  0,  0,   5,  2),   # May 16 — CPU wave
            (151,  8,  3,   0,  3),   # Jun 1
        ]

        rhel8_idx = 0
        random_keys = list(open_keys)
        random.shuffle(random_keys)
        rand_idx = 0

        for offset, n_new, n_os, n_cpu, n_decomm in waves:
            ev_date = start_date + timedelta(days=offset)
            if ev_date > today:
                break

            for _ in range(n_new):
                events.append((ev_date, 'new', None))

            # OS upgrades: prefer RHEL8 → RHEL9
            for _ in range(n_os):
                if rhel8_idx < len(rhel8_keys):
                    key = rhel8_keys[rhel8_idx]
                    rhel8_idx += 1
                    events.append((ev_date, 'os_upgrade', (key, 'RHEL9')))
                elif rand_idx < len(random_keys):
                    key = random_keys[rand_idx]
                    rand_idx += 1
                    new_os = random.choice(['Windows 2022', 'Ubuntu 22.04', 'RHEL9'])
                    events.append((ev_date, 'os_upgrade', (key, new_os)))

            # CPU upgrades: double CPU on random servers
            for _ in range(n_cpu):
                if rand_idx < len(random_keys):
                    key = random_keys[rand_idx]
                    rand_idx += 1
                    events.append((ev_date, 'cpu_upgrade', (key, 2)))

            # Decommissions
            for _ in range(n_decomm):
                if rand_idx < len(random_keys):
                    key = random_keys[rand_idx]
                    rand_idx += 1
                    events.append((ev_date, 'decomm', key))

        return events
