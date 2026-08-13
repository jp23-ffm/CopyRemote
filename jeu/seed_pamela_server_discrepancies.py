from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from discrepancies.models import ServerDiscrepancyPamela

# Real PAMELA per-server export sample for report_type=missing_LA (date 2026-08-13),
# transcribed as-is: (host, techfamily, area). We don't yet have real per-server exports for
# the other 5 report types (AD/ADDM/SA/EPO/CA) — see how_tools_are_assigned() below for how
# this same host list is deterministically (not randomly) augmented with those, purely to
# have non-empty demo data across all 6 dashboard gauges. That augmentation is fake, not real
# PAMELA output — only the LA tag + host/techfamily/area are real.
MISSING_LA_HOSTS = [
    ('CH7310PVS00001', 'Linux Server', 'APAC'),
    ('CIPHERTRUST', 'Linux Server', 'EMEA'),
    ('EURVLII100501', 'Linux Server', 'EMEA'),
    ('EURVLII116792', 'Linux Server', 'EMEA'),
    ('EURVLII124541', 'Linux Server', 'EMEA'),
    ('EURVLII127349', 'Linux Server', 'EMEA'),
    ('EURVLII130464', 'Linux Server', 'EMEA'),
    ('EURVLII131940', 'Linux Server', 'EMEA'),
    ('EURVLII133871', 'Linux Server', 'EMEA'),
    ('EURVLII134676', 'Linux Server', 'EMEA'),
    ('EURVLII135530', 'Linux Server', 'EMEA'),
    ('EURVLII136319', 'Linux Server', 'EMEA'),
    ('EURVLII136769', 'Linux Server', 'EMEA'),
    ('EURVLII138067', 'Linux Server', 'EMEA'),
    ('EURVLII138069', 'Linux Server', 'EMEA'),
    ('EURVLII138070', 'Linux Server', 'EMEA'),
    ('EURVLII138072', 'Linux Server', 'EMEA'),
    ('EURVLII138619', 'Linux Server', 'EMEA'),
    ('EURVLII138684', 'Linux Server', 'EMEA'),
    ('EURVLII138691', 'Linux Server', 'EMEA'),
    ('EURVLII138692', 'Linux Server', 'EMEA'),
    ('EURVLII138693', 'Linux Server', 'EMEA'),
    ('EURVLII138694', 'Linux Server', 'EMEA'),
    ('EURVLII138700', 'Linux Server', 'EMEA'),
    ('EURVLII138702', 'Linux Server', 'EMEA'),
    ('EURVLII138703', 'Linux Server', 'EMEA'),
    ('EURVLII138704', 'Linux Server', 'EMEA'),
    ('EURVLII138705', 'Linux Server', 'EMEA'),
    ('EURVLII138706', 'Linux Server', 'EMEA'),
    ('EURVLII138707', 'Linux Server', 'EMEA'),
    ('EURVLII138709', 'Linux Server', 'EMEA'),
    ('EURVLII138710', 'Linux Server', 'EMEA'),
    ('EURVLII138711', 'Linux Server', 'EMEA'),
    ('EURVLII138712', 'Linux Server', 'EMEA'),
    ('EURVLII138721', 'Linux Server', 'EMEA'),
    ('EURVLII138723', 'Linux Server', 'EMEA'),
    ('EURVLII140079', 'Linux Server', 'EMEA'),
    ('EURVLII140080', 'Linux Server', 'EMEA'),
    ('EURVLII140093', 'Linux Server', 'EMEA'),
    ('EURVLII143587', 'Linux Server', 'EMEA'),
    ('EURVLII143601', 'Linux Server', 'EMEA'),
    ('EURVLII143604', 'Linux Server', 'EMEA'),
    ('EURVLII143610', 'Linux Server', 'EMEA'),
    ('EURVLII144086', 'Linux Server', 'APAC'),
    ('EURVLII144446', 'Linux Server', 'EMEA'),
    ('EURVLII144449', 'Linux Server', 'EMEA'),
    ('EURVLII144451', 'Linux Server', 'EMEA'),
    ('EURVLII146438', 'Linux Server', 'EMEA'),
    ('EURVLII146446', 'Linux Server', 'EMEA'),
    ('EURVLII147226', 'Linux Server', 'EMEA'),
    ('EURVLII147681', 'Linux Server', 'EMEA'),
    ('EURVLII147682', 'Linux Server', 'EMEA'),
    ('EURVLII147687', 'Linux Server', 'EMEA'),
    ('EURVLII147700', 'Linux Server', 'EMEA'),
    ('EURVLII148035', 'Linux Server', 'EMEA'),
    ('EURVLII148064', 'Linux Server', 'EMEA'),
    ('EURVLII148065', 'Linux Server', 'EMEA'),
    ('EURVLII148068', 'Linux Server', 'EMEA'),
    ('EURVLII148088', 'Linux Server', 'EMEA'),
    ('EURVLII148464', 'Linux Server', 'EMEA'),
    ('EURVLII148490', 'Linux Server', 'EMEA'),
    ('EURVLII149156', 'Linux Server', 'EMEA'),
    ('EURVLII149158', 'Linux Server', 'EMEA'),
    ('EURVLII149160', 'Linux Server', 'EMEA'),
    ('EURVLII149228', 'Linux Server', 'EMEA'),
    ('EURVLII149229', 'Linux Server', 'EMEA'),
    ('EURVLII149230', 'Linux Server', 'EMEA'),
    ('EURVLII149372', 'Linux Server', 'EMEA'),
    ('EURVLII150885', 'Linux Server', 'EMEA'),
    ('EURVLII150892', 'Linux Server', 'EMEA'),
    ('EURVLII151142', 'Linux Server', 'EMEA'),
    ('EURVLII42550', 'Linux Server', 'EMEA'),
    ('EURVLII42558', 'Linux Server', 'EMEA'),
    ('EURVLII44715', 'Linux Server', 'EMEA'),
    ('EURVLII55938', 'Linux Server', 'EMEA'),
    ('EURVLII56010', 'Linux Server', 'EMEA'),
    ('EURVLII56459', 'Linux Server', 'EMEA'),
    ('EURVLII58228', 'Linux Server', 'EMEA'),
    ('EURVLII58240', 'Linux Server', 'EMEA'),
    ('EURVLII58678', 'Linux Server', 'EMEA'),
    ('EURVLII58969', 'Linux Server', 'EMEA'),
    ('EURVLII61260', 'Linux Server', 'EMEA'),
    ('EURVLII68564', 'Linux Server', 'EMEA'),
    ('EURVLII69528', 'Linux Server', 'EMEA'),
    ('EURVLII73784', 'Linux Server', 'EMEA'),
    ('EURVLII79704', 'Linux Server', 'EMEA'),
    ('EURVLII83875', 'Linux Server', 'EMEA'),
    ('EURVLII86186', 'Linux Server', 'EMEA'),
    ('EURVLII87669', 'Linux Server', 'EMEA'),
    ('EURVLII89153', 'Linux Server', 'EMEA'),
    ('EURVLII89619', 'Linux Server', 'EMEA'),
    ('EURVLII90570', 'Linux Server', 'EMEA'),
    ('EURVLII93630', 'Linux Server', 'EMEA'),
    ('EURVLII97721', 'Linux Server', 'EMEA'),
    ('GITHUB-POC-DEV-ECHONET-PRIMARY', 'Linux Server', 'EMEA'),
    ('LF-M01-NSX01A', 'Linux Server', 'EMEA'),
    ('LF-W01-NSX01A', 'Linux Server', 'EMEA'),
    ('LF-W01-NSX01B', 'Linux Server', 'EMEA'),
    ('LF-W01-NSX01C', 'Linux Server', 'EMEA'),
    ('NARVLII18815', 'Linux Server', 'AMER'),
    ('NARVLII18816', 'Linux Server', 'AMER'),
    ('NARVLII18818', 'Linux Server', 'AMER'),
    ('NARVLII24734', 'Linux Server', 'AMER'),
    ('NARVLII24735', 'Linux Server', 'AMER'),
    ('NARVLII27643', 'Linux Server', 'AMER'),
    ('NARVLII31058', 'Linux Server', 'AMER'),
    ('NARVLII31175', 'Linux Server', 'AMER'),
    ('NARVLII31176', 'Linux Server', 'AMER'),
    ('OS7110PHC00001', 'Hypervisor', 'APAC'),
    ('OS7201PHC00005', 'Hypervisor', 'APAC'),
    ('OS7201PHC00006', 'Hypervisor', 'APAC'),
    ('OS7210PHC00004', 'Hypervisor', 'APAC'),
    ('OS7310PVM00001', 'Hypervisor', 'APAC'),
    ('OS9511PHC00006', 'Hypervisor', 'EMEA'),
    ('OS9519PHC00005', 'Hypervisor', 'EMEA'),
    ('OS9550PHC00002', 'Hypervisor', 'EMEA'),
    ('OS9550PHC00003', 'Hypervisor', 'EMEA'),
    ('OS9591PHC00004', 'Hypervisor', 'EMEA'),
    ('OS9610PHC00005', 'Hypervisor', 'EMEA'),
    ('OS9610PHM00003', 'Hypervisor', 'EMEA'),
    ('OS9610PHM00004', 'Hypervisor', 'EMEA'),
    ('OS9619PHC00003', 'Hypervisor', 'EMEA'),
    ('OS9650PHC00002', 'Hypervisor', 'EMEA'),
    ('OS9650PHC00010', 'Hypervisor', 'EMEA'),
    ('OS9691PHC00004', 'Hypervisor', 'EMEA'),
    ('PARG0PMAASNO001', 'Appliance', 'EMEA'),
    ('PARS3PLKAFKA001', 'Linux Server', 'EMEA'),
    ('PARS3PLKAFKA002', 'Linux Server', 'EMEA'),
    ('PARS3PLKAFKA003', 'Linux Server', 'EMEA'),
    ('PARS3PLKAFKA004', 'Linux Server', 'EMEA'),
    ('PARS3PLKAFKA005', 'Linux Server', 'EMEA'),
    ('PARS3PLKAFKA006', 'Linux Server', 'EMEA'),
    ('PARVL1116361', 'Linux Server', 'EMEA'),
    ('SINVLII26578', 'Linux Server', 'APAC'),
    ('SINVLII26579', 'Linux Server', 'APAC'),
    ('SINVLII26580', 'Linux Server', 'APAC'),
    ('SINVLII26583', 'Linux Server', 'APAC'),
    ('SINVLII26585', 'Linux Server', 'APAC'),
    ('TEST-MK-GUM', 'Linux Server', 'EMEA'),
    ('TEST-MK-GUM2', 'Linux Server', 'EMEA'),
    ('TEURADJ', 'IV2-MP-STG - Linux Server', 'EMEA'),
    ('TEURVLII115593', 'IV2-MP-STG - Linux Server', 'EMEA'),
    ('TEURVLII115903', 'IV2-MP-STG - Linux Server', 'EMEA'),
    ('UK112', 'Linux Server', 'EMEA'),
    ('UK250', 'Linux Server', 'EMEA'),
    ('UK251', 'Linux Server', 'EMEA'),
    ('UK277', 'Linux Server', 'EMEA'),
]


def missing_tools_for(index):
    # Deterministic (not real) augmentation — every Nth host in the list also gets tagged for
    # one of the other 5 tools, just so the dashboard's 6 gauges aren't all-identical in dev.
    tools = ['LA']
    if index % 5 == 0:
        tools.append('SA')
    if index % 7 == 0:
        tools.append('AD')
    if index % 11 == 0:
        tools.append('ADDM')
    if index % 13 == 0:
        tools.append('EPO')
    if index % 17 == 0:
        tools.append('CA')
    return tools


class Command(BaseCommand):
    help = (
        'Reset ServerDiscrepancyPamela and reseed it with a real PAMELA missing_LA per-server '
        'export sample (dev substitute for the ODBC/CSV import), augmented with synthetic '
        'overlap on the other 5 tools for demo variety across the Pamela dashboard gauges'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', dest='snapshot_date', default=None,
            help='Snapshot date as YYYY-MM-DD (default: today)',
        )
        parser.add_argument(
            '--days', dest='days', type=int, default=1,
            help='Seed this many consecutive days ending at --date (default: 1), so the '
                 'Quality Trend chart and days_open have real history to show. Earlier days '
                 'get a shrinking prefix of MISSING_LA_HOSTS (fewer hosts flagged), reaching '
                 'the full real list only on --date — fake-but-plausible day-to-day movement, '
                 'not real historical PAMELA data.',
        )

    def handle(self, *args, **options):
        end_date = (
            date.fromisoformat(options['snapshot_date'])
            if options['snapshot_date'] else date.today()
        )
        n_days = max(1, options['days'])
        total_hosts = len(MISSING_LA_HOSTS)
        ramp_step = max(1, total_hosts // (2 * n_days)) if n_days > 1 else 0

        total_created = 0
        with transaction.atomic():
            for offset in range(n_days):
                days_before_end = n_days - 1 - offset
                snapshot_date = end_date - timedelta(days=days_before_end)
                host_count = max(1, total_hosts - days_before_end * ramp_step) if n_days > 1 else total_hosts
                hosts_today = MISSING_LA_HOSTS[:host_count]

                # Only wipe THIS date's rows — same convention as seed_pamela_data.
                ServerDiscrepancyPamela.objects.filter(snapshot_date=snapshot_date).delete()

                rows = [
                    ServerDiscrepancyPamela(
                        SERVER_ID=host, techfamily=techfamily, area=area,
                        missing_fields=','.join(missing_tools_for(i)),
                        snapshot_date=snapshot_date,
                    )
                    for i, (host, techfamily, area) in enumerate(hosts_today)
                ]
                ServerDiscrepancyPamela.objects.bulk_create(rows)
                total_created += len(rows)

        self.stdout.write(self.style.SUCCESS(
            f"ServerDiscrepancyPamela reseeded for {n_days} day(s) ending {end_date}: "
            f"{total_created} rows created"
        ))
