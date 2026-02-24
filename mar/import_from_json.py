import json
import datetime
import math
import os
import requests
import csv

from django.conf import settings
from django.db import connection as django_connection, transaction
from businesscontinuity.models import ServerUnique, Server, ServerStaging, ImportStatus

VARIATION_ALLOWED = 0.1  # 10%
DPR_API_URL="http://localhost:8000/api/get-json/"
DPR_FILE_PATH="C:\\Temp\\Django\\chimera\\dpr_saphir.json"
DPR_PATCH_FILE_PATH="C:\\Temp\\Django\\chimera\\pamela.json"
DPR_PATCH_FILE_GOLDENAPP_PATH="C:\\Temp\\Django\\chimera\\goldenapp.json"

API_TOKEN = "ded9a0a452b85bffab6dbe1f7e9cacbef34870cb"  #"9d35652a42e1713cbff77d6a1cc0c5ede3168051"
LOG_PATH="C:\\Temp\\Django\\chimera\\dpr_import.log"
AFFINITY_CORRECTION="C:\\Temp\\Django\\chimera\\vmaffinity.csv"

field_mapping = {
    "SERVER_ID": "SERVER_ID",
    "ITCONTINUITY_LEVEL": "SERVER_APM-DETAILS__ITCONTINUITYCRITICALITY",
    "DAP_NAME": "SNOW_SERVICE__U_LABEL",
    "DAP_AUID": "SNOW_AUID_VALUE",
    "DATACENTER": "PAMELA__DATACENTER",
    "TECH_FAMILY": "PAMELA__TECHFAMILY",
    "MACHINE_TYPE": "SERVER_MACHINE_TYPE_VALUE",
    "VM_TYPE": "PAMELA__VMTYPE",
    "AFFINITY": "PAMELA__AFFINITY",
    "VITAL_LEVEL": "SERVER_APM-SERVICES__VITALAPPLICATION",
    "DATABASE_TECHNO": "PAMELA_DATABASE_TECH",
    "DATABASE_DB_CI": "DATABASE_DB_CI_VALUE",
    "SUPPORT_GROUP": "SNOW_SERVER__SUPPORT_GROUP",
    "APPLICATION_SUPPORT_GROUP": "SNOW_APPLICATION__SUPPORT_GROUP",
    "IT_CLUSTER": "SERVER_APM-DETAILS__ITCLUSTER"
}


def write_log(message):
    print(message)
    with open(LOG_PATH, 'a') as log_file:
        log_file.write(message + '\n')
        

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
    

def recreate_staging_table_sqlite(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS businesscontinuity_serverstaging;")
        cursor.execute("PRAGMA table_info(businesscontinuity_server);")
        columns = cursor.fetchall()
        column_definitions = ", ".join([f"{col[1]} {col[2]}" for col in columns])
        create_table_sql = f"CREATE TABLE businesscontinuity_serverstaging ({column_definitions});"
        cursor.execute(create_table_sql)
        conn.commit()
    except sqlite3.Error as e:
        write_log(f"[{datetime.datetime.now()}] SQLite error: {e}")

    finally:
        cursor.close()
        conn.close()


def recreate_staging_table():
    with django_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS businesscontinuity_serverstaging;")
        cursor.execute("CREATE TABLE businesscontinuity_serverstaging (LIKE businesscontinuity_server INCLUDING ALL);")


def import_from_json_file(verbose=False):
    start_time = datetime.datetime.now()
    write_log(f"[{start_time}] Start import of the servers...")
    
    """
    try:
        if os.path.exists(DPR_FILE_PATH):
            write_log(f"[{start_time}] Backing up the existing JSON file...")
            backup_path = f"{DPR_FILE_PATH}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(DPR_FILE_PATH, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg    
    
    write_log(f"[{start_time}] Getting the json form DPR...")
    try:
        headers = {
            "Authorization": f"Token {API_TOKEN}"
        }
        response = requests.get(DPR_API_URL, headers=headers)
        response.raise_for_status()
        with open(DPR_FILE_PATH, 'wb') as f:
            f.write(response.content)
        write_log(f"[{datetime.datetime.now()}] JSON file successfully retrieved")
    except Exception as e:
        msg = f"Error during the API import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg
    """
    try:
        write_log(f"[{datetime.datetime.now()}] Reading the json...")
        with open(DPR_FILE_PATH, 'r') as f:
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

    # Load pamela information
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
        
    # Load goldenapp information
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

    write_log(f"[{datetime.datetime.now()}] Recreate the ServerStaging table...")

    db_default = settings.DATABASES['default']
    if db_default['ENGINE'] == 'django.db.backends.sqlite3':
        recreate_staging_table_sqlite(db_default['NAME'])
    else:  # PostgreSQL
        recreate_staging_table()

    FLUSH_SIZE = 5000
    staging_objs = []
    total_staging = 0
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

                if len(staging_objs) >= FLUSH_SIZE:
                    ServerStaging.objects.bulk_create(staging_objs, batch_size=1000)
                    total_staging += len(staging_objs)
                    staging_objs = []

                if verbose and (index % progress_interval == 0):
                    print(f"\r[{datetime.datetime.now()}] Processed {index} servers", end='', flush=True)

            if verbose:
                print("\r" + " " * 80, end='\r', flush=True)  # Clear the progress line

            # Last batch
            if staging_objs:
                ServerStaging.objects.bulk_create(staging_objs, batch_size=1000)
                total_staging += len(staging_objs)

            write_log(f"[{datetime.datetime.now()}] Created {total_staging} staging entries")
            
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



