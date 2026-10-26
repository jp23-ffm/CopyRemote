from django.core.management.base import BaseCommand
from monitor.models import GlobalHealthStatus

#from monitor.management.commands.status_checks import checks
import monitor.management.commands.status_checks as checks


class Command(BaseCommand):
    help = 'Update the global checks (tables, imports, certificat)' # To be lauched every hour

    def handle(self, *args, **options):
        self.stdout.write("Execute the global check...")
        
        GLOBAL_CHECKS = [
            # Table items count
            ("Business Continuity Server", lambda: checks.count_table_items(
                app_label="businesscontinuity", 
                model_name="Server",
                display_name="Entries - Business Continuity"
            )),
            ("Business Continuity ServerUnique", lambda: checks.count_table_items(
                app_label="businesscontinuity", 
                model_name="ServerUnique",
                display_name="Entries - Business Continuity"
            )),
            ("Inventory Server", lambda: checks.count_table_items(
                app_label="inventory", 
                model_name="Server",
                display_name="Entries - Inventory"
            )),
            ("Inventory ServerGroupSummary", lambda: checks.count_table_items(
                app_label="inventory", 
                model_name="ServerGroupSummary",
                display_name="Entries - Inventory"
            )),
             ("Discrepancies ServerDiscrepancy", lambda: checks.count_table_items(
                app_label="discrepancies", 
                model_name="ServerDiscrepancy",
                display_name="Entries - Discrepancies"
            )),

            # Imports status
            ("Last Import - Business Continuity", lambda: checks.check_businesscontinuity_last_import()),
            ("Last Import - Inventory", lambda: checks.check_inventory_last_import()),
            ("Last Import - Discrepancies", lambda: checks.check_discrepancies_last_import()),
            
            # SSL Certificate
            ("Check Certificate", lambda: checks.check_url_certificate(
                url="https://chimeraiaas.dev.echonet/login/"
            )),
        ]
        
        # Execute the checks
        checks_results = []
        overall_status = "OK"
        
        for check_name, check_fn in GLOBAL_CHECKS:
            try:
                result = check_fn()
                checks_results.append(result)
                
                if result["Status"] == "Error":
                    overall_status = "Error"
                elif result["Status"] == "Warning" and overall_status != "Error":
                    overall_status = "Warning"
                
                status_symbol = {
                    'OK': '✓',
                    'Warning': '⚠',
                    'Error': '✗'
                }.get(result["Status"], '?')
                
                self.stdout.write(f"  {status_symbol} {check_name}: {result['Status']}")
                
            except Exception as exc:
                error_result = {
                    "Name": check_name,
                    "Status": "Error",
                    "Details": f"Exception: {str(exc)}"
                }
                checks_results.append(error_result)
                overall_status = "Error"
                self.stderr.write(self.style.ERROR(f"  ✗ {check_name}: Error - {exc}"))
        
        try:
            GlobalHealthStatus.update_global_status(
                status=overall_status,
                checks_data={
                    'checks': checks_results,
                    'total_checks': len(checks_results),
                    'ok_count': sum(1 for c in checks_results if c['Status'] == 'OK'),
                    'warning_count': sum(1 for c in checks_results if c['Status'] == 'Warning'),
                    'error_count': sum(1 for c in checks_results if c['Status'] == 'Error'),
                }
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓Global checks updated: {overall_status} "
                    f"({len(checks_results)} checks performed)"
                )
            )
            
        except Exception as exc:
            self.stderr.write(
                self.style.ERROR(f"Error during the saving in the DB: {exc}")
            )
            raise
