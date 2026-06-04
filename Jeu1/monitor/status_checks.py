import datetime as dt
import math
import os
import psutil
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from django.apps import apps
from django.conf import settings
from django.core.cache import caches
from django.db import connections
from django.db.utils import OperationalError
from django.utils import timezone

from datetime import timedelta
from typing import Dict, Any, Optional
from urllib.parse import urlparse


# ----------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------
def check_database(display_name: Optional[str] = "Database") -> Dict[str, Any]:
    # Try a simple SELECT on the default DB
    
    payload: Dict[str, Any] = {
        "Name": f"{display_name}",
        "Status": "OK",
    }
    conn = connections["default"]
    try:
        conn.ensure_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            _ = cursor.fetchone()
        return payload
    except OperationalError as exc:
        payload["Status"] = "Error"
        payload["Details"] = exc
        return payload


# ----------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------
def count_table_items(*, display_name: Optional[str] = "", app_label: str, model_name: str, warning_maxthreshold: Optional[int] = None, error_maxthreshold: Optional[int] = None, warning_minthreshold: Optional[int] = None, error_minthreshold: Optional[int] = None,) -> Dict[str, Any]:

    payload: Dict[str, Any] = {
        "Name": f"{app_label}{display_name}: {model_name}",
        "Status": "OK",
    }
    # Resolve the model class
    try:
        model = apps.get_model(app_label, model_name)
        if model is None:
            payload["Status"] = "Error"
            payload["Details"] = f"The model {model_name} could not be resolved"
            return payload

    except Exception as exc:
        # Anything that prevents us from getting the model (mis‑spelling, app not installed, import error …) is a failure
        payload["Status"] = "Error"
        payload["Details"] = f"Unable to load model: {exc}"
        return payload

    # Perform the count
    try:
        count = model.objects.count()
    except Exception as exc:                  # DB problems, etc.
        payload["Status"] = "Error"
        payload["Details"] = f"Database error while counting rows: {exc}"
        return payload

    status_str = "OK"
    message: Optional[str] = None

    if error_maxthreshold is not None and count >= error_maxthreshold:
        status_str = "Error"
        message = f"Nb of entries {count} is above the Error threshold {error_maxthreshold}"
    elif warning_maxthreshold is not None and count >= warning_maxthreshold:
        status_str = "Warning"
        message = f"Nb of entries {count} is above the Warning threshold {warning_maxthreshold}"

    if error_minthreshold is not None and count <= error_minthreshold:
        status_str = "Error"
        message = f"Nb of entries {count} is below the Error threshold {error_minthreshold}"
    elif warning_minthreshold is not None and count <= warning_minthreshold:
        status_str = "Warning"
        message = f"Nb of entries {count} is below the Warning threshold {warning_minthreshold}"

    # Build the payload – we keep the same shape as the other checks
    payload: Dict[str, Any] = {
        "Name": f"{display_name}: {model_name}",
        "Status": status_str,
        "Details": f"Nb of entries: {count}",
    }
    if message:
        payload["Details"]["Message"] = message

    return payload


# ----------------------------------------------------------------------
# Last DB Import Status
# ----------------------------------------------------------------------
def check_last_import(import_model, model_name):
    last_import_status = import_model.objects.order_by('-date_import').first()
    
    if last_import_status:
        date_import = last_import_status.date_import
        formatted_date = timezone.localtime(date_import).strftime("%d.%m.%Y, %H:%M:%S")
        timediff = (timezone.now() - date_import).total_seconds() / 3600
        timediff = int(round(timediff))
        payload: Dict[str, Any] = {
            "Name": f"Last Import - {model_name}",
            "Status": "OK" if last_import_status.success == True else "Warning",
            "Details": f"Last DPR Import: {formatted_date}"
        }
        #if timediff > 30:  # Last import is too old > 30 hours
        #    payload["Status"] = "Warning"
        #    payload["Details"] = f"Last DPR Import: {formatted_date} ({timediff} hours ago)"
        
        return payload
    else:
        payload: Dict[str, Any] = {
            "Name": f"Last Import - {model_name}",
            "Status": "Error",
            "Details": "Last DPR Import: Unable to get the last import date"
        }    
    return payload

def check_businesscontinuity_last_import():
    from businesscontinuity.models import ImportStatus
    return check_last_import(ImportStatus, "Business Continuity")

def check_inventory_last_import():
    from inventory.models import ImportStatus
    return check_last_import(ImportStatus, "Inventory")

def check_discrepancies_last_import():
    from discrepancies.models import ImportStatus
    return check_last_import(ImportStatus, "Discrepancies")

def check_snapshot_status():
    from inventory.models import SnapshotStatus
    return check_last_import(SnapshotStatus, "Field Snapshots")


# ----------------------------------------------------------------------
# Disk / File‑system health (free space)
# ----------------------------------------------------------------------
def check_disk(display_name: Optional[str] = "Disk Space", path: str = "/", min_free_gb: float = 0.5) -> Dict[str, Any]:
    # Verify that the mount point has at least `min_free_gb` free
    payload: Dict[str, Any] = {
        "Name": display_name,
        "Status": "OK",
    }
    
    statvfs = os.statvfs(path)
    free_bytes = statvfs.f_frsize * statvfs.f_bavail
    free_gb = free_bytes / (1024**3)

    if free_gb < min_free_gb:
        payload["Status"] = "Warning"
        payload["Details"] = f"Free space on {path}: {free_gb:.2f} GB (< {min_free_gb} GB)"
    else:
        payload["Details"] = f"Free space on {path}: {free_gb:.2f} GB"

    return payload


# ----------------------------------------------------------------------
# Django Processes
# ----------------------------------------------------------------------
def get_django_processes():
    django_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
        try:
            if any('manage' in arg for arg in proc.info['cmdline']):   # replace manage with gunicorn
                django_processes.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return django_processes


def get_real_cpu_percent(process, interval=1.0):
    
    num_cores = psutil.cpu_count()  # Get the number of CPU cores
    cpu_usage = process.cpu_percent(interval=interval)  # Measure CPU usage over the specified interval
    real_cpu_percent = cpu_usage / num_cores  # Normalize the CPU usage by the number of cores
    return real_cpu_percent


def print_django_stats(display_name: Optional[str] = "Django Processes", cpu_threshold: Optional[float] = None, ram_threshold: Optional[float] = None, display_total: Optional[bool] = False):

    payload: Dict[str, Any] = {
        "Name": display_name,
        "Status": "OK",
    }
    processes = get_django_processes()

    if not processes:
        payload["Status"] = "Error"
        payload["Details"] = "No Django Process detected"
        return payload

    total_cpu = 0.0
    total_ram = 0.0    
    details = []
    
    for proc in processes:
        proc_pid = psutil.Process(proc['pid'])
        cpu_usage = get_real_cpu_percent(proc_pid, interval=1.0)
        ram_usage = proc['memory_info'].rss / (1024 * 1024)  # Convert to MB
        total_cpu += cpu_usage
        total_ram += ram_usage
        details.append({
            "Name": proc['name'],
            "PID": proc['pid'],
            "CPU": cpu_usage,
            "CPU2": proc['cpu_percent'],
            "RAM": ram_usage
        })

    payload["Details"] = details
    
    cpu_status = "OK" 
    ram_status = "OK"

    if cpu_threshold is not None and ram_threshold is not None:
        # Check thresholds
        cpu_status = "OK" if total_cpu <= cpu_threshold else "Warning"
        ram_status = "OK" if total_ram <= ram_threshold else "Warning"
        payload["Status"] = "OK" if cpu_status == "OK" and ram_status == "OK" else "Warning"
        
    if display_total == True:
        payload["Total"] = {
            "Total CPU": total_cpu,
            "Total RAM": total_ram
        }

    return payload


def get_gunicorn(display_name: Optional[str] = "Gunicorn Processes", proc_expected: Optional[int] = 2):
    count = 0
    for proc in psutil.process_iter(['pid', 'name', 'ppid']):
        if proc.info['name'] == 'gunicorn' and proc.info['ppid'] != 0:
            # Check if the parent process is also a gunicorn process
            parent_proc = psutil.Process(proc.info['ppid'])
            if parent_proc.name() == 'gunicorn':
                count += 1

    payload: Dict[str, Any] = {
        "Name": display_name,
        "Status": "OK",
        "Details": f"{count} processes found"
    }
    
    if count != proc_expected:
        payload["Status"] = "Warning"
        payload["Details"] = f"{count} processes found, {proc_expected} were expected"

    if count == 0:
        payload["Status"] = "Error"
        payload["Details"] = f"0 process found, {proc_expected} were expected"
        
    return payload  


def get_nginx(display_name: Optional[str] = "nginx Process", proc_expected: Optional[int] = 4):
    count = 0
    for proc in psutil.process_iter(['pid', 'name', 'ppid']):
        if proc.info['name'] == 'nginx' and proc.info['ppid'] != 0:
            # Check if the parent process is also a nginx process
            parent_proc = psutil.Process(proc.info['ppid'])
            if parent_proc.name() == 'nginx':
                count += 1

    payload: Dict[str, Any] = {
        "Name": display_name,
        "Status": "OK",
        "Details": f"{count} processes found"
    }
    
    if count < proc_expected:
        payload["Status"] = "Warning"
        payload["Details"] = f"{count} processes found, >={proc_expected} were expected"

    if count == 0:
        payload["Status"] = "Error"
        payload["Details"] = f"0 process found, >={proc_expected} were expected"
        
    return payload  


# ----------------------------------------------------------------------
# Uptime
# ----------------------------------------------------------------------

def get_uptime_via_proc() -> timedelta:
    # Return the system uptime as a timedelta object
    with open("/proc/uptime", "r", encoding="utf-8") as f:
        uptime_seconds = float(f.read().split()[0])
    return timedelta(seconds=uptime_seconds)

def check_system_uptime():
    # Return the exact boot timestamp (UTC)
    uptime = get_uptime_via_proc()
    boot_time_utc = datetime.utcnow() - uptime

    fmt: str = "%d.%m.%Y, %H:%M:%S"
    return boot_time_utc.strftime(fmt)


# ----------------------------------------------------------------------
# Certificate
# ----------------------------------------------------------------------

def _make_ssl_context() -> ssl.SSLContext:
    # Create a context that validates the server cert (default trust store)
    ctx = ssl.create_default_context()
    return ctx


def _extract_host_port(url: str) -> tuple[str, int]:
    # Parse the URL and return (hostname, port).  Defaults to 443 for https
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Unsupported scheme {parsed.scheme!r}. Use https://…")
    host = parsed.hostname
    if not host:
        raise ValueError("URL does not contain a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def get_cert_expiry(url: str) -> dict:

    # Connect to *url*, retrieve the leaf certificate and return expiry information

    host, port = _extract_host_port(url)
    ctx = _make_ssl_context()

    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert_dict = ssock.getpeercert()

    not_after  = dt.datetime.strptime(cert_dict["notAfter"],  "%b %d %H:%M:%S %Y %Z")
    not_after  = not_after.replace(tzinfo=dt.timezone.utc)

    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    remaining = not_after - now
    expired = remaining.total_seconds() <= 0

    def _rfc4514_name(name_seq):
        # name_seq is a tuple of tuples like ((('commonName', 'example.com'),), ...)
        parts = []
        for rdn in name_seq:
            for attr in rdn:
                parts.append(f"{attr[0]}={attr[1]}")
        return ", ".join(parts)

    info = {
        "not_after": not_after,
        "expired": expired,
        "days_left": max(remaining.days, 0),
     }
    return info


def check_url_certificate(url, display_name: Optional[str] = "Certificate"):

    payload: Dict[str, Any] = {
        "Name": display_name,
        "URL": url,
        "Status": "OK",
    }

    try:
        info = get_cert_expiry(url)
        payload["Details"] = f"Days until expiration: {info['days_left']}"
        return payload
        
    except Exception as exc:
        payload["Status"] = "Error"
        payload["Details"] = f"Could not retrieve the certificate: {exc}"
        return payload



