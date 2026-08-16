from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from discrepancies.models import ServerDiscrepancyPamela, PamelaDiscrepancyTracking, PamelaAnalysisSnapshot
from discrepancies.pamela_sync import sync_serverdiscrepancypamela, update_pamela_tracker

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
        'Reset ServerDiscrepancyPamela/PamelaDiscrepancyTracking/PamelaAnalysisSnapshot and '
        'reseed them with a real PAMELA missing_LA per-server export sample (dev substitute '
        'for the ODBC import), augmented with synthetic overlap on the other 5 tools for demo '
        'variety across the Pamela dashboard gauges. Reuses sync_serverdiscrepancypamela() / '
        'update_pamela_tracker() from analyze_pamela_discrepancies — same functions the real '
        'daily run calls — simulated day-by-day so days_open and the Quality Trend chart have '
        'realistic history instead of a single flat snapshot.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', dest='end_date', default=None,
            help='Last simulated day, as YYYY-MM-DD (default: today)',
        )
        parser.add_argument(
            '--days', dest='days', type=int, default=1,
            help='Simulate this many consecutive days ending at --date (default: 1), so the '
                 'Quality Trend chart and days_open have real history to show. Earlier days '
                 'get a shrinking prefix of MISSING_LA_HOSTS (fewer hosts flagged), reaching '
                 'the full real list only on --date — fake-but-plausible day-to-day movement, '
                 'not real historical PAMELA data.',
        )

    def handle(self, *args, **options):
        end_date = (
            date.fromisoformat(options['end_date'])
            if options['end_date'] else date.today()
        )
        n_days = max(1, options['days'])
        total_hosts = len(MISSING_LA_HOSTS)
        ramp_step = max(1, total_hosts // (2 * n_days)) if n_days > 1 else 0

        with transaction.atomic():
            ServerDiscrepancyPamela.objects.all().delete()
            PamelaDiscrepancyTracking.objects.all().delete()
            PamelaAnalysisSnapshot.objects.all().delete()

            # Anchored on the current time-of-day (not a fixed hour) so that, when --date is
            # today (the common case), the oldest simulated day lands exactly N*24h before
            # "now" — otherwise a fixed hour like 06:00 tested later in the day would undershoot
            # the days_open=N boundary by those extra hours (oldest_first_seen__lte=cutoff is a
            # strict elapsed-time comparison, not a calendar-day one).
            now_time = timezone.now().time()
            current = {}
            for offset in range(n_days):
                days_before_end = n_days - 1 - offset
                sim_date = end_date - timedelta(days=days_before_end)
                sim_datetime = timezone.make_aware(datetime.combine(sim_date, now_time))

                host_count = max(1, total_hosts - days_before_end * ramp_step) if n_days > 1 else total_hosts
                hosts_today = MISSING_LA_HOSTS[:host_count]

                current = {
                    host: {'techfamily': techfamily, 'area': area, 'missing': set(missing_tools_for(i))}
                    for i, (host, techfamily, area) in enumerate(hosts_today)
                }

                update_pamela_tracker(current, now=sim_datetime)

                tool_counts = {}
                for data in current.values():
                    for tool in data['missing']:
                        tool_counts[tool] = tool_counts.get(tool, 0) + 1
                PamelaAnalysisSnapshot.objects.create(
                    analysis_date=sim_datetime,
                    servers_with_any_missing=len(current),
                    tool_counts=tool_counts,
                )

            # Current-state table only needs the FINAL simulated day's result.
            created, updated, deleted = sync_serverdiscrepancypamela(current)

        self.stdout.write(self.style.SUCCESS(
            f"Pamela demo data reseeded for {n_days} day(s) ending {end_date}: "
            f"ServerDiscrepancyPamela {created} created / {updated} updated / {deleted} removed, "
            f"{n_days} PamelaAnalysisSnapshot row(s), tracker rebuilt day-by-day."
        ))
