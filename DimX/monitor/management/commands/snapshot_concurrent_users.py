from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import StatsConcurrentUsers


class Command(BaseCommand):
    help = 'Snapshot the number of active (non-expired) sessions into stats_concurrent_users.'

    def handle(self, *args, **options):
        now = timezone.now()
        active_count = Session.objects.filter(expire_date__gt=now).count()
        StatsConcurrentUsers.objects.create(active_users=active_count)
        self.stdout.write(
            self.style.SUCCESS(f'Snapshot recorded: {active_count} active sessions at {now:%Y-%m-%d %H:%M:%S}')
        )
