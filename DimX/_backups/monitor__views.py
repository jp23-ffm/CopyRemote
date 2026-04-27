#from django.shortcuts import render

import socket

from django.http import JsonResponse
from django.views import View
from django.utils import timezone

from monitor.models import HostHealthStatus, GlobalHealthStatus


"""class ClusterStatusView(View):
    # View to read the statuts of all hosts + the global checks from the DB
    
    STALE_THRESHOLD_SECONDS = 600  # 10 minutes for the hosts
    GLOBAL_STALE_THRESHOLD_SECONDS = 18000  # 5 hours for the global checks
    
    def get(self, request, *args, **kwargs):
        hosts = HostHealthStatus.objects.all().order_by('host_name')
        
        # Get the global checks
        try:
            global_health = GlobalHealthStatus.get_or_create_singleton()
        except:
            global_health = None
        
        if not hosts.exists() and not global_health:
            return JsonResponse({
                "cluster_status": "Unknown",
                "message": "No reported status yet",
                "timestamp": timezone.now().isoformat(),
                "hosts": [],
                "global_checks": None
            }, status=503)
        
        # ===== hosts =====
        hosts_data = []
        cluster_status = "OK"
        stale_hosts = []
        error_hosts = []
        warning_hosts = []
        
        for host in hosts:
            staleness = host.get_staleness_seconds()
            is_stale = host.is_stale(self.STALE_THRESHOLD_SECONDS)
            
            if is_stale:
                effective_status = "Stale"
                stale_hosts.append(host.host_name)
            else:
                effective_status = host.status
                if host.status == "Error":
                    error_hosts.append(host.host_name)
                elif host.status == "Warning":
                    warning_hosts.append(host.host_name)
            
            host_info = {
                "host_name": host.host_name,
                "status": effective_status,
                "reported_status": host.status,
                "last_updated": host.last_updated.isoformat() if host.last_updated else None,
                "staleness_seconds": round(staleness, 2) if staleness else None,
                "is_stale": is_stale,
                "hostname": host.hostname,
                "ip_address": host.ip_address,
                "version": host.version,
                "uptime": host.uptime,
                "checks_summary": {
                    "total": host.checks_data.get('total_checks', 0),
                    "ok": host.checks_data.get('ok_count', 0),
                    "warning": host.checks_data.get('warning_count', 0),
                    "error": host.checks_data.get('error_count', 0),
                },
                "checks": host.checks_data.get('checks', [])
            }
            
            hosts_data.append(host_info)
        
        # Statut des hosts
        if stale_hosts:
            cluster_status = "Degraded" if len(stale_hosts) < hosts.count() else "Critical"
        elif error_hosts:
            cluster_status = "Degraded" if len(error_hosts) < hosts.count() else "Critical"
        elif warning_hosts:
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
            
            # Take account of the global check for the whole status
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
                "total_hosts": hosts.count(),
                "healthy_hosts": hosts.count() - len(stale_hosts) - len(error_hosts),
                "stale_hosts": len(stale_hosts),
                "error_hosts": len(error_hosts),
                "warning_hosts": len(warning_hosts),
            },
            "hosts": hosts_data,
            "global_checks": global_checks_data
        }
        
        # Issues
        issues = []
        if stale_hosts:
            issues.append({
                "type": "stale",
                "message": f"host(s) haven't reported since {self.STALE_THRESHOLD_SECONDS}s",
                "affected_hosts": stale_hosts
            })
        if error_hosts:
            issues.append({
                "type": "error",
                "message": "host(s) on error",
                "affected_hosts": error_hosts
            })
        if global_checks_data and global_checks_data["is_stale"]:
            issues.append({
                "type": "global_stale",
                "message": f"Global checks not updated since {self.GLOBAL_STALE_THRESHOLD_SECONDS}s",
                "affected": "global_checks"
            })
        if global_checks_data and global_checks_data["status"] == "Error":
            issues.append({
                "type": "global_error",
                "message": "Global checks on error",
                "affected": "global_checks"
            })
        
        if issues:
            response["issues"] = issues
        
        http_status = 503 if cluster_status in ["Critical", "Degraded"] else 200

        return JsonResponse(response, status=http_status, json_dumps_params={'indent': 2})
"""

def get_cluster_status(simple=False):
    hosts = HostHealthStatus.objects.all().order_by('host_name')
    STALE_THRESHOLD_SECONDS = 600  # 10 minutes for the hosts
    GLOBAL_STALE_THRESHOLD_SECONDS = 7200  # 2 hours for the global checks

    # Get the global checks
    try:
        global_health = GlobalHealthStatus.get_or_create_singleton()
    except:
        global_health = None

    if not hosts.exists() and not global_health:
        return {
            "cluster_status": "Unknown",
            "message": "No reported status yet",
            "timestamp": timezone.now().isoformat()
        }, 503

    hostname = socket.gethostname()

    # ===== hosts =====
    cluster_status = "OK"
    stale_hosts = []
    error_hosts = []
    warning_hosts = []

    for host in hosts:
        staleness = host.get_staleness_seconds()
        is_stale = host.is_stale(STALE_THRESHOLD_SECONDS)

        if is_stale:
            stale_hosts.append(host.host_name)
        else:
            if host.status == "Error":
                error_hosts.append(host.host_name)
            elif host.status == "Warning":
                warning_hosts.append(host.host_name)

    # Statut des hosts
    if stale_hosts:
        cluster_status = "Degraded" if len(stale_hosts) < hosts.count() else "Critical"
    elif error_hosts:
        cluster_status = "Degraded" if len(error_hosts) < hosts.count() else "Critical"
    elif warning_hosts:
        cluster_status = "Warning"
    else:
        cluster_status = "OK"

    # ===== GLOBAL CHECKS =====
    if global_health:
        global_staleness = global_health.get_staleness_seconds()
        global_is_stale = global_health.is_stale(GLOBAL_STALE_THRESHOLD_SECONDS)

        # Take account of the global check for the whole status
        if global_is_stale:
            if cluster_status == "OK":
                cluster_status = "Warning"
        elif global_health.status == "Error":
            if cluster_status in ["OK", "Warning"]:
                cluster_status = "Degraded"
        elif global_health.status == "Warning":
            if cluster_status == "OK":
                cluster_status = "Warning"

    if simple:
        return {
            "cluster_status": cluster_status,
            "timestamp": timezone.now().isoformat()
        }, 200

    # ===== RESPONSE =====
    response = {
        "cluster_status": cluster_status,
        "hostname": hostname,
        "timestamp": timezone.now().isoformat(),
        "summary": {
            "total_hosts": hosts.count(),
            "healthy_hosts": hosts.count() - len(stale_hosts) - len(error_hosts),
            "stale_hosts": len(stale_hosts),
            "error_hosts": len(error_hosts),
            "warning_hosts": len(warning_hosts),
        },
        "hosts": [
            {
                "host_name": host.host_name,
                "status": "Stale" if host.is_stale(600) else host.status,
                "reported_status": host.status,
                "last_updated": host.last_updated.isoformat() if host.last_updated else None,
                "staleness_seconds": round(host.get_staleness_seconds(), 2) if host.get_staleness_seconds() else None,
                "is_stale": host.is_stale(600),
                "hostname": host.hostname,
                "ip_address": host.ip_address,
                "version": host.version,
                "uptime": host.uptime,
                "checks_summary": {
                    "total": host.checks_data.get('total_checks', 0),
                    "ok": host.checks_data.get('ok_count', 0),
                    "warning": host.checks_data.get('warning_count', 0),
                    "error": host.checks_data.get('error_count', 0),
                },
                "checks": host.checks_data.get('checks', [])
            } for host in hosts
        ],
        "global_checks": {
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
        } if global_health else None
    }

    # Issues
    issues = []
    if stale_hosts:
        issues.append({
            "type": "stale",
            "message": f"host(s) n'ont pas reporté depuis 600s",
            "affected_hosts": stale_hosts
        })
    if error_hosts:
        issues.append({
            "type": "error",
            "message": "host(s) en erreur",
            "affected_hosts": error_hosts
        })
    if global_health and global_is_stale:
        issues.append({
            "type": "global_stale",
            "message": f"Checks globaux non mis à jour depuis 7200s",
            "affected": "global_checks"
        })
    if global_health and global_health.status == "Error":
        issues.append({
            "type": "global_error",
            "message": "Checks globaux en erreur",
            "affected": "global_checks"
        })

    if issues:
        response["issues"] = issues

    http_status = 503 if cluster_status in ["Critical", "Degraded"] else 200

    return response, http_status
