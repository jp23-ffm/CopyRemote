from django.core.management.base import BaseCommand

from monitor.health import refresh_global_health


class Command(BaseCommand):
    help = 'Update the global checks (tables, imports, certificat)'  # To be lauched every hour (or every 15 min, snoozes expire)

    def handle(self, *args, **options):
        self.stdout.write("Execute the global check...")

        try:
            overall_status, results = refresh_global_health(
                log=lambda msg: self.stderr.write(self.style.ERROR(f"  ✗ {msg}"))
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Error during the saving in the DB: {exc}"))
            raise

        symbols = {'OK': '✓', 'Warning': '⚠', 'Error': '✗', 'Snoozed': '💤'}
        for r in results:
            self.stdout.write(f"  {symbols.get(r['Status'], '?')} {r.get('Name')}: {r['Status']}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓Global checks updated: {overall_status} ({len(results)} checks performed)"
            )
        )
