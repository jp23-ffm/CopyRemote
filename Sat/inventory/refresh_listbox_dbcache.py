# EXPERIMENTAL — companion to inventory/views_dbcache.py.
# Run manually after an import while comparing the DB-backed cache against
# the current LocMemCache behavior:
#   python manage.py refresh_listbox_dbcache
#
# If the comparison proves out, call refresh_listbox_dbcache() from
# swap_tables() in dbimport_inventory_csv.py (right after the successful
# commit) instead of running this by hand.

from django.core.management.base import BaseCommand

from inventory.views_dbcache import (
    get_field_labels,
    get_all_listbox_fields,
    get_serverunique_fields,
    batch_load_listbox_values,
)


def refresh_listbox_dbcache():
    json_data = get_field_labels()
    listbox_fields = get_all_listbox_fields(json_data)
    su_fields = get_serverunique_fields(json_data)
    return batch_load_listbox_values(listbox_fields, su_fields=su_fields, force_refresh=True)


class Command(BaseCommand):
    help = "Force-refresh the DB-backed ('longcache') listbox cache used by inventory/views_dbcache.py"

    def handle(self, *args, **options):
        result = refresh_listbox_dbcache()
        self.stdout.write(self.style.SUCCESS(
            f"Refreshed {len(result)} listbox fields in the 'longcache' DB cache."
        ))
