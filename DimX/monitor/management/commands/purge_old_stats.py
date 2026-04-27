from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from monitor.models import AuditConnection, StatsConcurrentUsers, StatsRequest


class Command(BaseCommand):
    help = 'Purge stats and audit data older than N days.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete records older than this many days (default: 90).',
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip confirmation prompt.',
        )

    def handle(self, *args, **options):
        days = options['days']
        if days < 7:
            raise CommandError('--days must be at least 7.')

        cutoff = timezone.now() - timedelta(days=days)
        cutoff_date = cutoff.date()

        counts = {
            'stats_requests': StatsRequest.objects.filter(date__lt=cutoff_date).count(),
            'audit_connections': AuditConnection.objects.filter(timestamp__lt=cutoff).count(),
            'stats_concurrent': StatsConcurrentUsers.objects.filter(snapshot_at__lt=cutoff).count(),
        }
        total = sum(counts.values())

        if total == 0:
            self.stdout.write('Nothing to purge.')
            return

        self.stdout.write(f'Records to delete (older than {days} days / before {cutoff_date}):')
        for table, count in counts.items():
            self.stdout.write(f'  {table}: {count:,}')
        self.stdout.write(f'  TOTAL: {total:,}')

        if not options['yes']:
            confirm = input('\nProceed? [y/N] ').strip().lower()
            if confirm != 'y':
                self.stdout.write('Aborted.')
                return

        StatsRequest.objects.filter(date__lt=cutoff_date).delete()
        AuditConnection.objects.filter(timestamp__lt=cutoff).delete()
        StatsConcurrentUsers.objects.filter(snapshot_at__lt=cutoff).delete()

        self.stdout.write(self.style.SUCCESS(f'Purged {total:,} records.'))
