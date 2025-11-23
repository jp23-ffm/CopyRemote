from django.http import JsonResponse
from django.views import View
from django.utils import timezone

from api.models import NodeHealthStatus, GlobalHealthStatus


class ClusterStatusView(View):
    """Vue qui lit les statuts de tous les nodes + les checks globaux depuis la DB."""
    
    STALE_THRESHOLD_SECONDS = 120  # 2 minutes pour les nodes
    GLOBAL_STALE_THRESHOLD_SECONDS = 7200  # 2 heures pour les checks globaux
    
    def get(self, request, *args, **kwargs):
        nodes = NodeHealthStatus.objects.all().order_by('node_name')
        
        # Récupérer les checks globaux
        try:
            global_health = GlobalHealthStatus.get_or_create_singleton()
        except:
            global_health = None
        
        if not nodes.exists() and not global_health:
            return JsonResponse({
                "cluster_status": "Unknown",
                "message": "Aucun node n'a encore reporté son statut",
                "timestamp": timezone.now().isoformat(),
                "nodes": [],
                "global_checks": None
            }, status=503)
        
        # ===== NODES =====
        nodes_data = []
        cluster_status = "OK"
        stale_nodes = []
        error_nodes = []
        warning_nodes = []
        
        for node in nodes:
            staleness = node.get_staleness_seconds()
            is_stale = node.is_stale(self.STALE_THRESHOLD_SECONDS)
            
            if is_stale:
                effective_status = "Stale"
                stale_nodes.append(node.node_name)
            else:
                effective_status = node.status
                if node.status == "Error":
                    error_nodes.append(node.node_name)
                elif node.status == "Warning":
                    warning_nodes.append(node.node_name)
            
            node_info = {
                "node_name": node.node_name,
                "status": effective_status,
                "reported_status": node.status,
                "last_updated": node.last_updated.isoformat() if node.last_updated else None,
                "staleness_seconds": round(staleness, 2) if staleness else None,
                "is_stale": is_stale,
                "hostname": node.hostname,
                "ip_address": node.ip_address,
                "version": node.version,
                "checks_summary": {
                    "total": node.checks_data.get('total_checks', 0),
                    "ok": node.checks_data.get('ok_count', 0),
                    "warning": node.checks_data.get('warning_count', 0),
                    "error": node.checks_data.get('error_count', 0),
                },
                "checks": node.checks_data.get('checks', [])
            }
            
            nodes_data.append(node_info)
        
        # Statut des nodes
        if stale_nodes:
            cluster_status = "Degraded" if len(stale_nodes) < nodes.count() else "Critical"
        elif error_nodes:
            cluster_status = "Degraded" if len(error_nodes) < nodes.count() else "Critical"
        elif warning_nodes:
            cluster_status = "Warning"
        else:
            cluster_status = "OK"
        
        # ===== GLOBAL CHECKS =====
        global_checks_data = None
        if global_health:
            global_staleness = global_health.get_staleness_seconds()
            global_is_stale = global_health.is_stale(self.GLOBAL_STALE_THRESHOLD_SECONDS)
            
            global_checks_data = {
                "status": "Stale" if global_is_stale else global_health.status,
                "reported_status": global_health.status,
                "last_updated": global_health.last_updated.isoformat() if global_health.last_updated else None,
                "staleness_seconds": round(global_staleness, 2) if global_staleness else None,
                "is_stale": global_is_stale,
                "checks_summary": {
                    "total": global_health.checks_data.get('total_checks', 0),
                    "ok": global_health.checks_data.get('ok_count', 0),
                    "warning": global_health.checks_data.get('warning_count', 0),
                    "error": global_health.checks_data.get('error_count', 0),
                },
                "checks": global_health.checks_data.get('checks', [])
            }
            
            # Prendre en compte les checks globaux dans le statut du cluster
            if global_is_stale:
                if cluster_status == "OK":
                    cluster_status = "Warning"
            elif global_health.status == "Error":
                if cluster_status in ["OK", "Warning"]:
                    cluster_status = "Degraded"
            elif global_health.status == "Warning":
                if cluster_status == "OK":
                    cluster_status = "Warning"
        
        # ===== RESPONSE =====
        response = {
            "cluster_status": cluster_status,
            "timestamp": timezone.now().isoformat(),
            "summary": {
                "total_nodes": nodes.count(),
                "healthy_nodes": nodes.count() - len(stale_nodes) - len(error_nodes),
                "stale_nodes": len(stale_nodes),
                "error_nodes": len(error_nodes),
                "warning_nodes": len(warning_nodes),
            },
            "nodes": nodes_data,
            "global_checks": global_checks_data
        }
        
        # Issues
        issues = []
        if stale_nodes:
            issues.append({
                "type": "stale",
                "message": f"Node(s) n'ont pas reporté depuis {self.STALE_THRESHOLD_SECONDS}s",
                "affected_nodes": stale_nodes
            })
        if error_nodes:
            issues.append({
                "type": "error",
                "message": "Node(s) en erreur",
                "affected_nodes": error_nodes
            })
        if global_checks_data and global_checks_data["is_stale"]:
            issues.append({
                "type": "global_stale",
                "message": f"Checks globaux non mis à jour depuis {self.GLOBAL_STALE_THRESHOLD_SECONDS}s",
                "affected": "global_checks"
            })
        if global_checks_data and global_checks_data["status"] == "Error":
            issues.append({
                "type": "global_error",
                "message": "Checks globaux en erreur",
                "affected": "global_checks"
            })
        
        if issues:
            response["issues"] = issues
        
        http_status = 503 if cluster_status in ["Critical", "Degraded"] else 200
        return JsonResponse(response, status=http_status, json_dumps_params={'indent': 2})
