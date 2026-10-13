import datetime

from django.core.management.base import BaseCommand, CommandError

from businesscontinuity.changes import DEFAULT_CHUNK_SIZE, iter_change_row_chunks, iter_csv_lines


class Command(BaseCommand):
    help = "Export Business Continuity changes (global_history + LP action histories) to CSV for a date range."

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', help='Start date YYYY-MM-DD (default: today)')
        parser.add_argument('--to', dest='date_to', help='End date YYYY-MM-DD, inclusive (default: --from)')
        parser.add_argument('--hostname', help='Restrict to hostnames containing this value')
        parser.add_argument('--user', help='Restrict to users containing this value')
        parser.add_argument('--source', help='Restrict to one source (e.g. "Bulk Edit", "BC Rules")')
        parser.add_argument('--chunk-size', type=int, default=DEFAULT_CHUNK_SIZE,
                            help=f'Servers read per query (default: {DEFAULT_CHUNK_SIZE})')
        parser.add_argument('--output', help='Output CSV path (default: bc_changes_<from>_<to>.csv)')

    def handle(self, *args, **options):
        try:
            d_from = (datetime.date.fromisoformat(options['date_from'])
                      if options['date_from'] else datetime.date.today())
            d_to = datetime.date.fromisoformat(options['date_to']) if options['date_to'] else d_from
        except ValueError:
            raise CommandError('Dates must be in YYYY-MM-DD format.')
        if d_to < d_from:
            raise CommandError('--to must be greater than or equal to --from.')
        if options['chunk_size'] < 1:
            raise CommandError('--chunk-size must be >= 1.')

        output = options['output'] or f"bc_changes_{d_from}_{d_to}.csv"

        count = 0

        def counted(chunks):
            nonlocal count
            for rows in chunks:
                count += len(rows)
                yield rows

        chunks = iter_change_row_chunks(
            d_from, d_to,
            hostname=options['hostname'], user=options['user'], source=options['source'],
            chunk_size=options['chunk_size'],
        )
        # BOM is emitted by iter_csv_lines, so plain utf-8 here
        with open(output, 'w', newline='', encoding='utf-8') as f:
            for block in iter_csv_lines(counted(chunks)):
                f.write(block)

        self.stdout.write(self.style.SUCCESS(f"{count} change(s) from {d_from} to {d_to} written to {output}"))
