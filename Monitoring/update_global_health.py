from django.core.management.base import BaseCommand
from api.models import GlobalHealthStatus

# Import tes fonctions de checks existantes
from api.management.commands.status_checks import checks


class Command(BaseCommand):
    help = 'Met à jour les checks globaux (tables, imports, certificat) - À lancer toutes les heures'

    def handle(self, *args, **options):
        self.stdout.write("Exécution des checks globaux...")
        
        # Liste des checks globaux (ceux qui ne dépendent pas d'un host)
        GLOBAL_CHECKS = [
            # Comptage des tables
            ("Servers view (reportapp)", lambda: checks.count_table_items(
                app_label="reportapp", 
                model_name="Server",
                display_name="Servers view (reportapp)"
            )),
            ("Servers view (businesscontinuity)", lambda: checks.count_table_items(
                app_label="businesscontinuity", 
                model_name="Server",
                display_name="Servers view (businesscontinuity)"
            )),
            ("Servers view (businesscontinuity) ServerUnique", lambda: checks.count_table_items(
                app_label="businesscontinuity", 
                model_name="ServerUnique",
                display_name="Servers view (businesscontinuity) ServerUnique"
            )),
            ("Servers view (inventory)", lambda: checks.count_table_items(
                app_label="inventory", 
                model_name="Server",
                display_name="Servers view (inventory)"
            )),
            ("Inventory ServerGroupSummary", lambda: checks.count_table_items(
                app_label="inventory", 
                model_name="ServerGroupSummary",
                display_name="Inventory ServerGroupSummary"
            )),
            
            # Status des imports
            ("Business Continuity Last Import", lambda: checks.check_businesscontinuity_last_import()),
            ("Inventory Last Import", lambda: checks.check_inventory_last_import()),
            
            # Certificat SSL
            ("Check Certificate", lambda: checks.check_url_certificate(
                url="https://chimeralaas.dev.echonet/login/"
            )),
        ]
        
        # Exécuter tous les checks globaux
        checks_results = []
        overall_status = "OK"
        
        for check_name, check_fn in GLOBAL_CHECKS:
            try:
                result = check_fn()
                checks_results.append(result)
                
                # Déterminer le statut global
                if result["Status"] == "Error":
                    overall_status = "Error"
                elif result["Status"] == "Warning" and overall_status != "Error":
                    overall_status = "Warning"
                
                # Log du résultat
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
        
        # Sauvegarder en DB
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
                    f"\n✓ Checks globaux mis à jour: {overall_status} "
                    f"({len(checks_results)} checks effectués)"
                )
            )
            
        except Exception as exc:
            self.stderr.write(
                self.style.ERROR(f"Erreur lors de la sauvegarde en DB: {exc}")
            )
            raise
