import socket
from django.core.management.base import BaseCommand
from django.conf import settings
from api.management.commands.status_checks import checks
from api.models import NodeHealthStatus


class Command(BaseCommand):
    help = 'Met à jour le statut de santé du node actuel (checks spécifiques au host)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--node-name',
            type=str,
            help='Nom du node (défaut: depuis settings.CURRENT_NODE_NAME ou hostname)',
        )

    def handle(self, *args, **options):
        # Déterminer le nom du node
        node_name = options.get('node_name')
        if not node_name:
            node_name = getattr(settings, 'CURRENT_NODE_NAME', None)
        if not node_name:
            node_name = socket.gethostname()
        
        self.stdout.write(f"Mise à jour du statut pour le node: {node_name}")
        
        # Récupérer les infos système
        hostname = socket.gethostname()
        ip_address = self._get_ip_address()
        version = getattr(settings, 'APP_VERSION', 'unknown')
        
        # Liste des checks SPÉCIFIQUES AU HOST (pas les checks globaux)
        HOST_CHECKS = [
            ("Database Check", lambda: checks.check_database(display_name="Database")),
            ("Disk Space", lambda: checks.check_disk(path="/", min_free_gb=1)),
            ("Django Processes", lambda: checks.print_django_stats(
                display_name="Django Processes",
                cpu_threshold=None,
                ram_threshold=None,
                display_total=False
            )),
        ]
        
        # Exécuter tous les checks
        checks_results = []
        overall_status = "OK"
        
        for check_name, check_fn in HOST_CHECKS:
            try:
                result = check_fn()
                checks_results.append(result)
                
                # Déterminer le statut global
                if result["Status"] == "Error":
                    overall_status = "Error"
                elif result["Status"] == "Warning" and overall_status != "Error":
                    overall_status = "Warning"
                    
            except Exception as exc:
                error_result = {
                    "Name": check_name,
                    "Status": "Error",
                    "Details": f"Exception: {str(exc)}"
                }
                checks_results.append(error_result)
                overall_status = "Error"
                self.stderr.write(self.style.ERROR(f"Error in check '{check_name}': {exc}"))
        
        # Sauvegarder en DB
        try:
            NodeHealthStatus.update_node_status(
                node_name=node_name,
                status=overall_status,
                checks_data={
                    'checks': checks_results,
                    'total_checks': len(checks_results),
                    'ok_count': sum(1 for c in checks_results if c['Status'] == 'OK'),
                    'warning_count': sum(1 for c in checks_results if c['Status'] == 'Warning'),
                    'error_count': sum(1 for c in checks_results if c['Status'] == 'Error'),
                },
                hostname=hostname,
                ip_address=ip_address,
                version=version
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Statut mis à jour: {overall_status} "
                    f"({len(checks_results)} checks effectués)"
                )
            )
            
        except Exception as exc:
            self.stderr.write(
                self.style.ERROR(f"Erreur lors de la sauvegarde en DB: {exc}")
            )
            raise
    
    def _get_ip_address(self):
        """Récupère l'adresse IP du serveur."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None
