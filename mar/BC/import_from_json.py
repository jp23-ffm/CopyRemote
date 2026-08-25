import csv
import datetime
import json
import math
import os
import requests
import ssl

from pathlib import Path
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager

from collections import OrderedDict
from django.conf import settings
from django.db import connection as django_connection, transaction

from businesscontinuity.models import ServerUnique, Server, ServerStaging, ImportStatus
from inventory.models import Server as InventoryServer

VARIATION_ALLOWED = 0.15  # 10%

DPR_CONFIG_JSON_PATH="/data/DPR_DATA/conf/dpr_saphir_conf.json"
DPR_FILE_PATH="/data/DPR_DATA/dpr_saphir_businesscontinuity.json"
DPR_CONTINUITY_SAPHIR_URL="https://dpr-backend.group.echonet/export/asset_saphir_data/chimera_dpr_saphir_conf?compress=false&filter=*&format=json"

DPR_CONFIG_JSON_PATCH_PATH="/data/DPR_DATA/conf/dpr_pamela_conf.json"
DPR_PATCH_FILE_PATH="/data/DPR_DATA/dpr_pamela_businesscontinuity.json"
DPR_CONTINUITY_PAMELA_URL="https://dpr-backend.group.echonet/export/pamela_server/chimera_dpr_pamela_conf?compress=false&filter=*&format=json"

DPR_SAPHIR_NODB_CONFIG_JSON_PATH="/data/DPR_DATA/conf/dpr_saphir_conf.json"
DPR_SAPHIR_NODB_FILE_PATH="/data/DPR_DATA/dpr_saphir_businesscontinuity_nodb.json"
DPR_CONTINUITY_SAPHIR_NODB_URL="https://dpr-backend.group.echonet/export/asset_saphir_data/chimera_dpr_saphir_nodb_conf?compress=false&filter=*&format=json"

DPR_PATCH_FILE_GOLDENAPP_PATH="/data/DPR_DATA/dpr_goldenapp_businesscontinuity.json"

DPR_SAPHIR_ENRICHED_FILE_PATH="/data/DPR_DATA/dpr_saphir_businesscontinuity_fix.json"

DPR_API_URL="https://dpr-backend.group.echonet:443/export/dynamic"

LOG_PATH="/data/DPR_DATA/logs/import_dpr_data.log"
AFFINITY_CORRECTION="/data/DPR_DATA/vmaffinity.csv"

field_mapping = {
    "SERVER_ID": "SERVER_ID",
    "ITCONTINUITY_LEVEL": "SERVER_APM-DETAILS__ITCONTINUITYCRITICALITY",
    "DAP_NAME": "SNOW_SERVICE__U_LABEL",
    "DAP_AUID": "SNOW_AUID_VALUE",
    "DATACENTER": "PAMELA__DATACENTER",
    # Not present in the Saphir/Pamela BC feed — resolved from inventory.Server instead,
    # via a bulk lookup (see resolve_environments()) injected into each entry under this
    # synthetic key so it flows through the same clean_value()/model_fields machinery as
    # every other field below.
    "ENVIRONMENT": "_ENVIRONMENT_RESOLVED",
    "TECH_FAMILY": "PAMELA__TECHFAMILY",
    "MACHINE_TYPE": "SERVER_MACHINE_TYPE_VALUE",
    "VM_TYPE": "PAMELA__VMTYPE",
    "AFFINITY": "PAMELA__AFFINITY",
    "VITAL_LEVEL": "SERVER_APM-SERVICES__VITALAPPLICATION",
    "DATABASE_TECHNO": "PAMELA_DATABASE_TECH",
    "DATABASE_DB_CI": "DATABASE_DB_CI_VALUE",
    "SUPPORT_GROUP": "SNOW_SERVER__SUPPORT_GROUP",
    "APPLICATION_SUPPORT_GROUP": "SNOW_APPLICATION__SUPPORT_GROUP",
    "IT_CLUSTER": "SERVER_APM-DETAILS__ITCLUSTER",
    "COUNTRY": "PAMELA__COUNTRY"
}

FULL_FIELDS = [
    "SERVER_ID",
    "SERVER_APM-DETAILS__ITCONTINUITYCRITICALITY",
    "SNOW_SERVICE__U_LABEL",
    "SNOW_AUID_VALUE",
    "PAMELA__DATACENTER",
    "PAMELA__TECHFAMILY",
    "SERVER_MACHINE_TYPE_VALUE",
    "PAMELA__VMTYPE",
    "PAMELA__AFFINITY",
    "PAMELA_DATABASE_TECH",          # optional – ignored for diff comparison
    "DATABASE_DB_CI_VALUE",          # optional – ignored for diff comparison
    "SERVER_APM-SERVICES__VITALAPPLICATION",
    "SNOW_SERVER__SUPPORT_GROUP",
    "SERVER_APM-DETAILS__ITCLUSTER",
    "PAMELA__COUNTRY"
]

IGNORED_FIELDS = {"PAMELA_DATABASE_TECH", "DATABASE_DB_CI_VALUE"}


def write_log(message):
    print(message)
    with open(LOG_PATH, 'a') as log_file:
        log_file.write(message + '\n')


# To solve the [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]
class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)


# Cache field lengths
field_lengths = {
    field: (
        ServerStaging._meta.get_field(field).max_length
        if hasattr(ServerStaging._meta.get_field(field), 'max_length')
        else None
    )
    for field in field_mapping.keys()
}


def clean_value(value, field_name):
    """ Clean and truncate string values based on the field length from the model. """
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "none":
        return "EMPTY"

    if not isinstance(value, str):
        value = str(value)

    value = value.replace("\r\n", "")

    max_length = field_lengths.get(field_name)
    if max_length and len(value) > max_length:
        return value[:max_length]

    return value


def resolve_environments(hostnames) -> dict:
    """
    Bulk-resolve ENVIRONMENT from inventory.Server for a collection of
    SERVER_ID (hostnames), in a single query.

    The Saphir/Pamela BC feed doesn't carry an ENVIRONMENT field, so it's
    sourced from inventory.Server instead — a single SERVER_ID__in query,
    not one lookup per hostname (this runs once for the whole import, ~45k
    hostnames, so a single bulk pass keeps it cheap regardless of index
    health on inventory_server).

    Assumes ENVIRONMENT is consistent across duplicate SERVER_ID rows in
    inventory (one hostname = several app/database rows, same environment).
    """
    hostnames = set(h.strip().upper() for h in hostnames if h)
    if not hostnames:
        return {}
    return dict(
        InventoryServer.objects
        .filter(SERVER_ID__in=hostnames)
        .values_list('SERVER_ID', 'ENVIRONMENT')
    )


def download_json(url: str, dest_path: str) -> None:

    write_log(f"[{datetime.datetime.now()}] Downloading {dest_path} from {url}")
    with requests.get(url, stream=True, timeout=30, verify=False) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:                 # filter out keep‑alive chunks
                    f.write(chunk)
    

def load_json(path: Path) -> list[dict]:

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalise_saphir_nodb(records: list[dict]) -> list[dict]:
    for rec in records:
        rec.setdefault("PAMELA_DATABASE_TECH", None)
        rec.setdefault("DATABASE_DB_CI_VALUE", None)
    return records


def comparison_key(rec: dict) -> tuple:
    # Hashable tuple that excludes the two optional fields
    return tuple(rec.get(f) for f in FULL_FIELDS if f not in IGNORED_FIELDS)
    

def make_ordered(rec: dict) -> OrderedDict:
    # Return an OrderedDict that follows FULL_FIELDS order
    return OrderedDict((field, rec.get(field)) for field in FULL_FIELDS)
        
        
def enrich_saphir(saphir_path, saphir_nodb_path):
    try:
        
        # Backup the existing enriched file
        if os.path.exists(DPR_SAPHIR_ENRICHED_FILE_PATH):
            write_log(f"[{datetime.datetime.now()}] Backing up the existing enriched Saphir file...")
            backup_path = f"{DPR_SAPHIR_ENRICHED_FILE_PATH}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(DPR_SAPHIR_ENRICHED_FILE_PATH, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing enriched Saphir file to back up.")
        
        write_log(f"[{datetime.datetime.now()}] Enrich {saphir_path} with {saphir_nodb_path}")
        saphir_records = load_json(Path(saphir_path))
        saphir_nodb_records = normalise_saphir_nodb(load_json(Path(saphir_nodb_path)))

        saphir_key_set = {comparison_key(r) for r in saphir_records}
        diff_records = [r for r in saphir_nodb_records if comparison_key(r) not in saphir_key_set]

        groups = {}
        for rec in saphir_records:
            key = (rec.get("SERVER_ID"), rec.get("SNOW_AUID_VALUE"))
            groups.setdefault(key, []).append(rec)

        synthetic_entries = []
        for _, records in groups.items():
            if any(r.get("DATABASE_DB_CI_VALUE") is not None for r in records):
                template = records[0].copy()
                template["PAMELA_DATABASE_TECH"] = None
                template["DATABASE_DB_CI_VALUE"] = None
                synthetic_entries.append(template)

        combined = saphir_records + synthetic_entries + diff_records
        combined.sort(key=lambda r: (r.get("SERVER_ID") is None, r.get("SERVER_ID")))

        ordered_output = [make_ordered(r) for r in combined]

        diff_path = Path(DPR_SAPHIR_ENRICHED_FILE_PATH)

        with diff_path.open("w", encoding="utf-8") as f:
            f.write("[\n")
            for i, entry in enumerate(ordered_output):
                line = json.dumps(entry, ensure_ascii=False)
                # add a comma after every line except the last one
                if i < len(ordered_output) - 1:
                    line += ","
                f.write(line + "\n")
            f.write("]\n")

        write_log(f"[{datetime.datetime.now()}] {len(saphir_records)} original saphir records")
        write_log(f"[{datetime.datetime.now()}] {len(synthetic_entries)} synthetic entries added")
        write_log(f"[{datetime.datetime.now()}] {len(diff_records)} genuine differences detected")
        #write_log(f"[{datetime.datetime.now()}] All {len(ordered_output)} entries written (sorted by SERVER_ID) to {diff_path.resolve()}")
        return True, "Enrichment successful"
        
    except Exception as e:
        msg = f"Error during the enrichment of Saphir data: {e}"
        return False, msg
        

def recreate_staging_table():
    with django_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS businesscontinuity_serverstaging;")
        cursor.execute("CREATE TABLE businesscontinuity_serverstaging (LIKE businesscontinuity_server INCLUDING ALL);")


def import_from_json_file(verbose=False):
    start_time = datetime.datetime.now()
    write_log(f"[{start_time}] Start import of the servers...")
    
    # DPR Saphir Import 
    """
    try:
        if os.path.exists(DPR_FILE_PATH):
            write_log(f"[{start_time}] Backing up the existing Saphir JSON file...")
            backup_path = f"{DPR_FILE_PATH}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(DPR_FILE_PATH, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing Saphir file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg    
    
    write_log(f"[{start_time}] Getting the Saphir JSON from DPR...")
    try:
        download_json(DPR_CONTINUITY_SAPHIR_URL, DPR_FILE_PATH)
        write_log(f"[{datetime.datetime.now()}] Saphir JSON file successfully retrieved")
    except Exception as e:
        msg = f"Error during the Saphir Import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
    """

    # DPR Saphir No DB Import    
    """
    try:
        if os.path.exists(DPR_SAPHIR_NODB_FILE_PATH):
            write_log(f"[{start_time}] Backing up the existing Saphir NoDB JSON file...")
            backup_path = f"{DPR_SAPHIR_NODB_FILE_PATH}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(DPR_SAPHIR_NODB_FILE_PATH, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing Saphir NoDB file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
    
    write_log(f"[{start_time}] Getting the Saphir NoDB JSON from DPR...")
    try:
        download_json(DPR_CONTINUITY_SAPHIR_NODB_URL, DPR_SAPHIR_NODB_FILE_PATH)
        write_log(f"[{datetime.datetime.now()}] Saphir NoDB JSON file successfully retrieved")
    except Exception as e:
        msg = f"Error during the Saphir NoDB Import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
    """

    # DPR Pamela API Import
    """
    try:
        if os.path.exists(DPR_PATCH_FILE_PATH):
            write_log(f"[{start_time}] Backing up the existing Pamela JSON file...")
            backup_path = f"{DPR_PATCH_FILE_PATH}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(DPR_PATCH_FILE_PATH, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing Pamela file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    write_log(f"[{start_time}] Getting the Pamela JSON from DPR...")    
    try:
        download_json(DPR_CONTINUITY_PAMELA_URL, DPR_PATCH_FILE_PATH)
        write_log(f"[{datetime.datetime.now()}] Saphir JSON file successfully retrieved")
    except Exception as e:
        msg = f"Error during the Pamela Import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
    """

    # Check for the presence and size of files
    files_to_check = [DPR_FILE_PATH, DPR_PATCH_FILE_PATH, DPR_SAPHIR_NODB_FILE_PATH]
    for file_path in files_to_check:
        if not os.path.exists(file_path):
            msg = f"File {file_path} not found"
            ImportStatus.objects.create(success=False, message=msg)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg
        elif os.path.getsize(file_path) < 1024 * 1024:  # 1 MB
            msg = f"File {file_path} is too small (less than 1 MB)"
            ImportStatus.objects.create(success=False, message=msg)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg

    files_to_check = [DPR_PATCH_FILE_GOLDENAPP_PATH]
    for file_path in files_to_check:
        if not os.path.exists(file_path):
            msg = f"File {file_path} not found"
            ImportStatus.objects.create(success=False, message=msg)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg
        elif os.path.getsize(file_path) < 300000:  # 300 kb
            msg = f"File {file_path} is too small (less than 1 MB)"
            ImportStatus.objects.create(success=False, message=msg)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg

    # Enrich the Saphir data
    enrich_result, enrich_msg = enrich_saphir(DPR_FILE_PATH, DPR_SAPHIR_NODB_FILE_PATH)
    if not enrich_result:
        ImportStatus.objects.create(success=False, message=enrich_msg)
        write_log(f"[{datetime.datetime.now()}] {enrich_msg}")
        return False, enrich_msg

    # Load Saphir information
    try:
        write_log(f"[{datetime.datetime.now()}] Reading the json...")
        with open(DPR_SAPHIR_ENRICHED_FILE_PATH, 'r') as f:  # Use the enriched version
            data = json.load(f)
    except Exception as e:
        msg = f"Error reading the JSON: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    if not isinstance(data, list):
        msg = "Invalid JSON format for the saphir data: list expected"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
        
    # Load Pamela information
    try:
        with open(DPR_PATCH_FILE_PATH, 'r') as pamela_file:
            pamela_data = json.load(pamela_file)
    except Exception as e:
        msg = f"Error reading pamela.json: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    if not isinstance(pamela_data, list):
        msg = "Invalid JSON format for the pamela data: list expected"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    # Load GoldenApp information
    try:
        with open(DPR_PATCH_FILE_GOLDENAPP_PATH, 'r') as goldenapp_file:
            goldenapp_data = json.load(goldenapp_file)
    except Exception as e:
        msg = f"Error reading goldenapp.json: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    if not isinstance(goldenapp_data, list):
        msg = "Invalid JSON format for the goldenapp data: list expected"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    # Create a mapping from pamela.json
    pamela_mapping = {}
    for entry in pamela_data:
        key = (entry.get("SERVER_ID").strip().upper(), entry.get("SNOW_AUID_VALUE"))
        pamela_mapping[key] = {
            "SNOW_APPLICATION__U_CONTINUITY_LEVEL": entry.get("SNOW_APPLICATION__U_CONTINUITY_LEVEL"),
            "SNOW_APPLICATION__U_VITAL_ASSET": entry.get("SNOW_APPLICATION__U_VITAL_ASSET"),
            "SNOW_APPLICATION__SUPPORT_GROUP": entry.get("SNOW_APPLICATION__SUPPORT_GROUP")
        }

    # Create the cluster mapping from golden_application
    goldenapp_mapping = {}
    for entry in goldenapp_data:
        key = entry.get("APM-DETAILS__DAPAUID")
        goldenapp_mapping[key] = {
            "APM-DETAILS__ITCLUSTER": entry.get("APM-DETAILS__ITCLUSTER")
        }

    old_count = Server.objects.count()
    new_count = len(data)

    if old_count > 0:
        variation = abs(new_count - old_count) / old_count
        if variation > VARIATION_ALLOWED:
            msg = f"Variation too big ({variation:.2%}), import cancelled"
            ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg

    # Load affinity information
    affinity_file_present = os.path.exists(AFFINITY_CORRECTION)
    
    if affinity_file_present:

        write_log(f"[{datetime.datetime.now()}] Reading the affinity corrections...")
        try:
            with open(AFFINITY_CORRECTION, 'r') as affinity_file:
                affinity_reader = csv.DictReader(affinity_file)
                affinity_data = [row for row in affinity_reader]
        except Exception as e:
            msg = f"Error reading affinity.csv: {e}"
            ImportStatus.objects.create(success=False, message=msg)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg

        # Create a mapping from affinity.csv
        affinity_mapping = {}
        for entry in affinity_data:
            server_id = entry.get("server_id").strip().lower()
            affinity_mapping[server_id] = entry.get("affinity").strip().upper()
    else:
        write_log(f"[{datetime.datetime.now()}] No affinity correction file. Skipping...")

    # Resolve ENVIRONMENT from inventory.Server in one bulk query (not in the DPR feed)
    write_log(f"[{datetime.datetime.now()}] Resolving ENVIRONMENT from inventory...")
    environment_mapping = resolve_environments(entry.get("SERVER_ID") for entry in data)
    write_log(f"[{datetime.datetime.now()}] Resolved ENVIRONMENT for {len(environment_mapping)} hostnames")

    write_log(f"[{datetime.datetime.now()}] Recreate the ServerStaging table...")

    db_default = settings.DATABASES['default']
    recreate_staging_table()

    staging_objs = []
    created_uniques = 0
    index = 0
    progress_interval=1000

    try:
        write_log(f"[{datetime.datetime.now()}] Enumerating and preparing the ServerStaging and ServerUnique entries to create...")
        with transaction.atomic():
            existing_servers_uniques = {su.hostname: su for su in ServerUnique.objects.all()}

            for entry in data:
                index = index+1
                hostname = entry.get("SERVER_ID")
                if not hostname:
                    continue

                # Distinguish "not present in inventory at all" (MISSING) from "present but
                # blank there" (falls through to clean_value()'s normal None -> EMPTY handling)
                inventory_key = hostname.strip().upper()
                if inventory_key in environment_mapping:
                    entry["_ENVIRONMENT_RESOLVED"] = environment_mapping[inventory_key]
                else:
                    entry["_ENVIRONMENT_RESOLVED"] = "MISSING"

                unique, created = ServerUnique.objects.get_or_create(
                    hostname=hostname,
                    defaults={ 'priority_asset': 'EMPTY', 'in_live_play': 'EMPTY', 'action_during_lp': 'EMPTY', 'action_during_lp_history': None,
                        'original_action_during_lp': 'EMPTY', 'original_action_during_lp_history': None, 'cluster': 'EMPTY', 'cluster_type': 'EMPTY' }
                )
                if created:
                    created_uniques += 1

                # Correct the values based on pamela.json
                key = (hostname.strip().upper(), entry.get("SNOW_AUID_VALUE"))
                if key in pamela_mapping:
                    entry["SERVER_APM-DETAILS__ITCONTINUITYCRITICALITY"] = pamela_mapping[key]["SNOW_APPLICATION__U_CONTINUITY_LEVEL"]
                    entry["SERVER_APM-SERVICES__VITALAPPLICATION"] = pamela_mapping[key]["SNOW_APPLICATION__U_VITAL_ASSET"]
                    entry["SNOW_APPLICATION__SUPPORT_GROUP"] = pamela_mapping[key].get("SNOW_APPLICATION__SUPPORT_GROUP", "EMPTY")

                # Correct the Cluster
                key = entry.get("SNOW_AUID_VALUE")
                if key in goldenapp_mapping:
                    entry["SERVER_APM-DETAILS__ITCLUSTER"] = goldenapp_mapping[key]["APM-DETAILS__ITCLUSTER"]

                # Update affinity value from csv file if necessary
                if affinity_file_present:
                    server_id = entry.get("SERVER_ID").strip().lower()
                    if server_id in affinity_mapping:
                        entry["PAMELA__AFFINITY"] = affinity_mapping[server_id]

                model_fields = {
                    ServerStaging._meta.get_field(m).name: clean_value(entry.get(v), m)
                    for m, v in field_mapping.items()
                }
                staging_objs.append(ServerStaging(
                    server_unique=unique,
                    **model_fields
                ))

                if verbose and (index % progress_interval == 0):
                    print(f"\r[{datetime.datetime.now()}] Processed {index} servers", end='', flush=True)

            if verbose:
                print("\r" + " " * 80, end='\r', flush=True)  # Clear the progress line
                
            write_log(f"[{datetime.datetime.now()}] Creating the ServerStaging and ServerUnique entries...")  
            ServerStaging.objects.bulk_create(staging_objs, batch_size=1000)
            write_log(f"[{datetime.datetime.now()}] Created {len(staging_objs)} staging entries")
            
    except Exception as e:
        msg = f"Error during the creation of ServerStaging and ServerUnique entries: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        write_log("----------------------------------------------------------------------------")
        return False, msg
        
    try:
        write_log(f"[{datetime.datetime.now()}] Swapping ServerStaging -> Server")
        with django_connection.cursor() as cursor:
            cursor.execute("BEGIN;")
            cursor.execute("DROP TABLE IF EXISTS businesscontinuity_serverbackup;")
            cursor.execute("ALTER TABLE businesscontinuity_server RENAME TO businesscontinuity_serverbackup;")
            cursor.execute("ALTER TABLE businesscontinuity_serverstaging RENAME TO businesscontinuity_server;")
            cursor.execute("COMMIT;")

        end_time = datetime.datetime.now()
        total_duration = end_time - start_time
        msg = f"Import successful: {new_count} entries imported, {created_uniques} unique servers created"
        ImportStatus.objects.create(success=True, message=msg, nb_entries_created=new_count)
        write_log(f"[{end_time}] {msg}")
        write_log(f"[{end_time}] Total duration for import: {total_duration}")
        write_log("----------------------------------------------------------------------------")

        return True, msg

    except Exception as e:
        msg = f"Error during the swap staging -> prod: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        write_log("----------------------------------------------------------------------------")
        return False, msg
