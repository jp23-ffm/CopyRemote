import json
import datetime
import math
import os
import requests
import django
import csv
import gc

from django.conf import settings
from django.db import connection as django_connection, transaction
from inventory.models import Server, ServerGroupSummary, ImportStatus, ServerStaging, ServerGroupSummaryStaging
from collections import defaultdict

from requests.adapters import HTTPAdapter, ssl

VARIATION_ALLOWED = 0.1  # 10%
LOG_PATH="/data/DPR_DATA/logs/import_dpr_pamela_inventory.log"

DPR_FILE_PATH_CONF={ "PROD": "/data/DPR_DATA/conf/dpr_pamela_inventory_conf_prod.json", 
                     "STG": "/data/DPR_DATA/conf/dpr_pamela_inventory_conf_stg.json",
                     "DEV": "/data/DPR_DATA/conf/dpr_pamela_inventory_conf_dev.json",
                     "OTHER": "/data/DPR_DATA/conf/dpr_pamela_inventory_conf_other.json"
                   }
                   
DPR_FILE_PATH_CSV={ "PROD": "/data/DPR_DATA/dpr_pamela_inventory_prod.csv",
                    "STG": "/data/DPR_DATA/dpr_pamela_inventory_stg.csv",
                    "DEV": "/data/DPR_DATA/dpr_pamela_inventory_dev.csv",
                    "OTHER": "/data/DPR_DATA/dpr_pamela_inventory_other.csv"
                  }

DPR_URL={ "PROD": "https://dpr-backend.group.echonet/export/pamela_server/chimera_dpr_pamela_inventory_conf_prod?compress=false&filter=*&format=csv",
          "STG": "https://dpr-backend.group.echonet/export/pamela_server/chimera_dpr_pamela_inventory_conf_stg?compress=false&filter=*&format=csv",
          "DEV": "https://dpr-backend.group.echonet/export/pamela_server/chimera_dpr_pamela_inventory_conf_dev?compress=false&filter=*&format=csv",
          "OTHER": "https://dpr-backend.group.echonet/export/pamela_server/chimera_dpr_pamela_inventory_conf_other?compress=false&filter=*&format=csv" 
        }


field_mapping = { 
    "APP_SECPROFILE": "APM_ALL__APPSECPROFILE",
    "APP_DESCRIPTION": "APM-DETAILS__APPLICATIONDESCRIPTION",
    "APP_MANAGER": "APM-DETAILS__APPLICATIONMANAGER",
    "APP_CRITICALITY": "APM-DETAILS__CRITICALITY",
    "APP_ITCLUSTER": "APM-DETAILS__ITCLUSTER",
    "APP_ITCONTINUITYCRITICALITY": "APM-DETAILS__ITCONTINUITYCRITICALITY",
    "APP_OWNERBUSINESSLINE": "APM_ALL__OWNERBUSINESSLINE",
    "APP_PRODUCTIONDOMAINMANAGER": "APM-DETAILS__PRODUCTIONDOMAINMANAGER",
    "APP_PRODUCTIONMANAGER": "APM-DETAILS__PRODUCTIONMANAGER",
    "APP_VITALAPP": "APM-DETAILS__VITALAPPLICATION",
    "APP_NAME_VALUE": "APPLICATION_NAME_VALUE",
    "APP_AUID_VALUE": "APPLICATION_AUID_VALUE",
    "APP_BAMPLUS_MANAGER_EMAIL": "BAMPLUS-APPLICATIONMANAGERS_EMAIL",
    "APP_BAMPLUS_EMAIL": "BAMPLUS-APPLICATIONS_EMAIL",
    "APP_BAMPLUS_BUSINESSLINEOWNER_EMAIL": "BAMPLUS-BUSINESSLINEOWNERS_EMAIL",
    "APP_BAMPLUS_DEVELOPMENTMANAGER_EMAIL": "BAMPLUS-DEVELOPMENTMANAGERS_EMAIL",
    "APP_BAMPLUS_INFRASTRUCTUREMANAGER_EMAIL": "BAMPLUS-INFRASTRUCTUREMANAGERS_EMAIL",
    "CAPSULE_PRODUCT": "CAPSULE-REF-SERVERS__DPI",
    "ECOSYSTEM": "CAPSULE-REF-SERVERS__ECOSYSTEM",
    "SUBSCRIPTION_ID": "CAPSULE-REF-SERVERS__SUB_ID",
    "SUBSCRIPTION_OWNER": "CAPSULE-REF-SERVERS__OWNER",
    "SUBSCRIPTION_STATE": "CAPSULE-REF-SERVERS__STATE",
    "APP_SUPPORTGROUP_EMAIL": "K9-APPLICATIONS__ITAPPLICATIONSUPPORTGROUPS.K9-APPLICATIONS__EMAIL",
    "APP_SUPPORTGROUP_NAME": "K9-APPLICATIONS__ITAPPLICATIONSUPPORTGROUPS.K9-APPLICATIONS__NAME",
    "OBSO_HW_ENDOFEXTENDEDDATE": "OBSO_MAP__HW_ENDOFEXTENDEDDATE",
    "OPENSTACK_LINKS": "OPENSTACK__FLAVOR.OPENSTACK__LINKS.OPENSTACK__HREF",
    "OPENSTACK_HOST": "OPENSTACK__KVM_HOST",
    "OPENSTACK_POWERSTATE": "OPENSTACK__KVM_VM_STATE",
    "AFFINITY": "PAMELA__AFFINITY",
    "REGION": "PAMELA__AREA",
    "ASSETGEN_CABINET": "PAMELA__ASSETGEN_CABINET",
    "ASSETGEN_ROOM": "PAMELA__ASSETGEN_ROOM",
    "CITY": "PAMELA__CITY",
    "COUNTRY": "PAMELA__COUNTRY",
    "CPU": "PAMELA__CPULOGICALTHREAD",
    "DOMAIN": "PAMELA__AD_DOMAIN",
    "PAMELA_DATACENTER": "PAMELA__DATACENTER",
    "DECOMREQ": "PAMELA__DECOMREQ",
    "ENVIRONMENT": "PAMELA__ENVIRONMENT",
    "FQDN": "PAMELA__FQDN",
    "HYPERVISOR": "PAMELA__HYPERVISOR",
    "IDRAC_IP": "PAMELA__IDRACIP",
    "IDRAC_NAME": "PAMELA__IDRACNAME",
    "INFRAVERSION": "PAMELA__INFRAVERSION",
    "IPADDRESS": "PAMELA__IPADDRESS",
    "LIVE_STATUS": "PAMELA__LIVE_STATUS_FINAL",
    "MANUFACTURER": "PAMELA__MANUFACTURER",
    "MODEL": "PAMELA__MODEL",
    "VLAN": "PAMELA__NETIP",
    "NETMASK": "PAMELA__NETMASK",
    "NETWORKID": "PAMELA__NETWORKID",
    "NETWORKNAME": "PAMELA__NETWORKNAME",
    "OBSO_HWPURCHASEDATE": "PAMELA__OBSO__HWPURCHASEDATE",
    "OPENSTACK_INFRA": "PAMELA__OG_INFRA",
    "OS": "PAMELA__OS",
    "OSFAMILY": "PAMELA__OSFAMILY",
    "OSFULLVERSION": "PAMELA__OSFULLVERSION",
    "OSSHORTNAME": "PAMELA__OSSHORTNAME",
    "PAAS_COMMENT": "PAMELA__PAAS_COMMENT",
    "PAAS_PHASE": "PAMELA__PAAS_PHASE",
    "PAAS_REQUESTER": "PAMELA__PAAS_REQUESTER",
    "PARKPLACEENDON": "PAMELA__PARKPLACEENDON",
    "PARKPLACESTARTON": "PAMELA__PARKPLACESTARTON",
    "PERIMETER": "PAMELA__PERIMETER",
    "PAMELA_PRODUCT": "PAMELA__PRODUCT",
    "PROVISIONNINGREQ": "PAMELA__PROVISIONNINGREQ",
    "SERIAL": "PAMELA__SERIAL",
    "SHORT_ENVIRONMENT": "PAMELA__SHORT_ENVIRONMENT",
    "SNOW_STATUS": "PAMELA__SNOWITG_STATUS",
    "SNOW_SUPPORTGROUP": "PAMELA__SNOWITG_SUPPORTGROUP",
    "SUBPERIMETER": "PAMELA__SUBPERIMETER",
    "SUBTECHFAMILY": "PAMELA__SUBTECHFAMILY",
    "TECHFAMILY": "PAMELA__TECHFAMILY",
    "VMTYPE": "PAMELA__VMTYPE",
    "PAMELA_VPIC_CLUSTER": "PAMELA__VPIC_CLUSTER",
    "SNOW_APPLICATION_VALUE": "SERVER_APPLICATION_VALUE",
    "SNOW_APPLICATION_AUID": "SNOW_AUID_VALUE",
    "SNOW_APPLICATION_NAME": "SNOW_APPLICATION__U_LABEL",
    "SNOW_DATACENTER": "SERVER_DATACENTER_VALUE",
    "DISK": "SERVER_DISK_VALUE",
    "SERVER_ID": "SERVER_ID",
    "SERVER_IP": "SERVER_IP_VALUE",
    "MACHINE_TYPE": "SERVER_MACHINE_TYPE_VALUE",
    "RAM": "SERVER_RAM_VALUE",
    "SERVER_ORPHAN": "SNOW_SERVER__FLAG_ORPHAN",
    "VPIC_CLUSTER": "VPIC__CLUSTER_NAME",
    "VPIC_DATACENTER": "VPIC__DATACENTER",
    "VPIC_DATASTORE": "VPIC__DATASTORE_NAME",
    "VPIC_HOST": "VPIC__HOST_NAME",
    "VPIC_OWNER": "VPIC__OWNER_UID",
    "VPIC_POWERSTATE": "VPIC__POWERSTATE",
    "VPIC_RESOURCEPOOL": "VPIC__RESOURCEPOOL",
    "VPIC_VCNAME": "VPIC__VCNAME",
    "VPIC_VMGROUPS": "VPIC__VMGROUPS",
    "PAMELA_ADDM_LASTSEEN": "PAMELA__ADDM_LASTSEEN",
}


# Cache field lengths
field_lengths = {
    field: (
        Server._meta.get_field(field).max_length
        if hasattr(Server._meta.get_field(field), 'max_length')
        else None
    )
    for field in field_mapping.keys()
}


# To solve the [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]
class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)


def write_log(message):
    print(message)
    with open(LOG_PATH, 'a') as log_file:
        log_file.write(message + '\n')


def clean_value(value, field_name):
    # Clean and truncate string values based on the field length from the model
    if value is None or value == "null" or value == "":
        return "EMPTY"

    if not isinstance(value, str):
        value = str(value)

    if "\r\n" in value or "\\r\\n" in value:
        value = value.replace("\\r\\n", "")
        value = value.replace("\r\n", "")

    max_length = field_lengths.get(field_name)
    if max_length and len(value) > max_length:
        return value[:max_length]
        
    if field_name == "OBSO_HWPURCHASEDATE" or field_name == "OBSO_HW_ENDOFEXTENDEDDATE":
        try:
            timestamp = int(value) / 1000  # Convert milliseconds to seconds
            dt = datetime.datetime.fromtimestamp(timestamp) # Convert to datetime object
            value = dt.strftime('%d.%m.%Y')  # Format the datetime object to a human-readable string
        except (ValueError, OverflowError):
            pass # If conversion fails, return the original value

    return value


"""
def get_DPR_data(name, json_path):
    write_log(f"[{datetime.datetime.now()}] Start import of the servers ({name})...")

    try:
        csv_path=DPR_FILE_PATH_CSV[name]
        if os.path.exists(csv_path):
            write_log(f"[{datetime.datetime.now()}] Backing up the existing JSON file...")
            backup_path = f"{csv_path}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(csv_path, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    write_log(f"[{datetime.datetime.now()}] Getting the csv from DPR ({name})...")
    with open(json_path, 'r') as file:
        json_data = json.load(file)
    try:
        session = requests.Session()
        session.mount('https://', TLSAdapter())
        response = session.post(DPR_API_URL, json=json_data, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:   # Save the response to the output file
            with open(csv_path, 'wb') as raw_file:
                raw_file.write(response.content)
            write_log(f"[{datetime.datetime.now()}] csv file successfully retrieved")
    except Exception as e:
        msg = f"Error during the API import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    return True, "DPR Import successful"
"""


def get_DPR_data(name, url):
    write_log(f"[{datetime.datetime.now()}] Start import of the servers ({name})...")

    try:
        csv_path=DPR_FILE_PATH_CSV[name]
        if os.path.exists(csv_path):
            write_log(f"[{datetime.datetime.now()}] Backing up the existing JSON file...")
            backup_path = f"{csv_path}.bak"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(csv_path, backup_path)
            write_log(f"[{datetime.datetime.now()}] Backup created: {backup_path}")
        else:
            write_log(f"[{datetime.datetime.now()}] No existing file to back up.")
    except Exception as e:
        msg = f"Error during the file backup: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    write_log(f"[{datetime.datetime.now()}] Getting the csv from DPR ({name})...")
    try:
        with requests.get(url, stream=True, timeout=30, verify=False) as resp:
            resp.raise_for_status()
            with open(csv_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:                 # filter out keep‑alive chunks
                        f.write(chunk)
                write_log(f"[{datetime.datetime.now()}] csv file successfully retrieved")
            
    except Exception as e:
        msg = f"Error during the API import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg

    return True, "DPR Import successful"
    

def recreate_staging_table():
    with django_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS inventory_serverstaging;")
        cursor.execute("CREATE TABLE inventory_serverstaging (LIKE inventory_server INCLUDING ALL);")
        cursor.execute("DROP TABLE IF EXISTS inventory_servergroupsummarystaging;")
        cursor.execute("CREATE TABLE inventory_servergroupsummarystaging (LIKE inventory_servergroupsummary INCLUDING ALL);")


def analyze_server_fields(server_list):
    #Analyze fields to determine constant vs variable - optimized version

    if len(server_list) == 1:  # Single server - all fields are constant
        server = server_list[0]
        constant_fields = {}
        for field in server._meta.fields:
            if field.name not in ['id', 'created_at', 'updated_at']:
                value = getattr(server, field.name)
                if value is not None:
                    constant_fields[field.name] = str(value)
        return {
            'constant': constant_fields,
            'variable': {}
        }
        
    field_values = defaultdict(list)  # Multiple servers - analyze field variations
        
    for server in server_list:
        for field in server._meta.fields:
            if field.name not in ['id', 'created_at', 'updated_at']:
                value = getattr(server, field.name)
                if value is not None:
                    str_value = str(value)
                    if str_value not in field_values[field.name]:
                        field_values[field.name].append(str_value)
        
    constant_fields = {}
    variable_fields = {}
        
    for field_name, values in field_values.items():
        if len(values) == 1:
            constant_fields[field_name] = list(values)[0]
        else:
            # Limit preview to avoid very large JSON
            preview_values = list(values)[:5]  # Max 5 values in preview
            variable_fields[field_name] = {
                'count': len(values),
                'preview': f"{len(values)} values (>5)" if len(values) > 5 else " | ".join(preview_values)
            }
        
    return {
        'constant': constant_fields,
        'variable': variable_fields
    }


def count_all_csv():
    newtotal=0
    
    for csv_path in DPR_FILE_PATH_CSV.values():
        csvfix_path = csv_path.replace('.csv', '_fixed.csv')
        with open(csvfix_path, 'r') as file:
            reader = csv.reader(file)
            newtotal+=sum(1 for row in reader)

    return newtotal


def fix_DPR_data(name, csv_file_path):

    # Streaming consolidation with semicolon delimiter and proper quoting
    # Groups rows where only K9 fields differ and concatenates those K9 values
    # Remove double OPENSTACK entries

    write_log(f"[{datetime.datetime.now()}] Starting consolidation for {csv_file_path}...")
    
    groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(list)})  # List to store groups
    k9_prefixes = ['K9-APPLICATIONS']
    
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL) # Use semicolon delimiter with proper quote handling
        fieldnames = reader.fieldnames

        fieldnames = [field.strip('"').strip() for field in fieldnames]  # Clean fieldnames (remove quotes if present)
        
        # Identify K9 and non-K9 columns
        k9_cols = [col for col in fieldnames if any(prefix in col for prefix in k9_prefixes)]
        non_k9_cols = [col for col in fieldnames if col not in k9_cols]
        openstack_skipped = 0

        row_count = 0
        
        for row in reader:
            row_count += 1
            
            # Skip row if the condition is met
            href_value = row.get('OPENSTACK__FLAVOR.OPENSTACK__LINKS.OPENSTACK__HREF', '').strip('"').strip()
            if href_value.startswith('HTTPS://OPENSTACK-APAC02-CORE-PROD.XMP.NET.INTRA:8774/FLAVORS/'):
                openstack_skipped = openstack_skipped + 1
                continue
            
            # Create a group key based on ALL non-K9 fields, strip quotes and whitespace from values
            group_key_parts = []
            for col in non_k9_cols:
                value = row.get(col, '').strip('"').strip()
                group_key_parts.append(value)
            
            group_key = '|||'.join(group_key_parts)
            
            # Store non-K9 values (only from first occurrence)
            if not groups[group_key]['non_k9']:
                groups[group_key]['non_k9'] = {col: row.get(col, '').strip('"').strip() for col in non_k9_cols}
            
            # Accumulate unique K9 values for each K9 column
            for k9_col in k9_cols:
                value = row.get(k9_col, '').strip('"').strip()
                if value and value.upper() not in ['N/A', 'NAN', 'NONE', 'NULL', '']:  # Only add non-empty and non-N/A values
                    if value not in groups[group_key]['k9_values'][k9_col]:
                        groups[group_key]['k9_values'][k9_col].append(value)
            
    write_log(f"[{datetime.datetime.now()}] Processed {row_count} rows into {len(groups)} unique groups, Reduction: {row_count - len(groups)} duplicate K9 entries removed, Openstack removed: {openstack_skipped}")
    output_path = csv_file_path.replace('.csv', '_fixed.csv')
    write_log(f"[{datetime.datetime.now()}] Writing consolidated data to {output_path}...")
    
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)  # Use semicolon delimiter with quotes around all fields
        writer.writeheader()
        
        written_count = 0
        
        for group_key, group_data in groups.items():
            row_out = group_data['non_k9'].copy()  # Build consolidated row
            
            # Add concatenated K9 values
            for k9_col in k9_cols:
                values = group_data['k9_values'].get(k9_col, [])
                if values:
                    row_out[k9_col] = ' | '.join(values)
                else:
                    row_out[k9_col] = ''
            
            writer.writerow(row_out)
            written_count += 1
            
    consolidated_count = len(groups)
    
    write_log(f"[{datetime.datetime.now()}] File written successfully")
    
    # Free the RAM
    groups.clear()
    gc.collect()


def fill_table(name, csv_path):

    try:
        write_log(f"[{datetime.datetime.now()}] Reading the CSV in chunks ({name})...")

        chunk_size = 50000  # Define the chunk size
        staging_objs = []
        created_uniques = 0
        index = 0
        progress_interval = 10000 

        csvfix_path = csv_path.replace('.csv', '_fixed.csv')
        with open(csvfix_path, 'r') as f:
            reader = csv.DictReader(f, delimiter=';')
            for entry in reader:
                staging_data = {}
                for model_field, csv_field in field_mapping.items():
                    value = entry.get(csv_field)
                    staging_data[model_field] = clean_value(value, model_field)

                staging_objs.append(ServerStaging(**staging_data))
                index += 1

                if index % chunk_size == 0:
                    write_log(f"[{datetime.datetime.now()}] Bulk creating {chunk_size} ServerStaging entries...")
                    ServerStaging.objects.bulk_create(staging_objs)
                    staging_objs = []  # Clear the list for the next chunk

                if index % progress_interval == 0:
                    write_log(f"[{datetime.datetime.now()}] Processed {index} entries...")
                     
        # Bulk create any remaining entries
        if staging_objs:
            write_log(f"[{datetime.datetime.now()}] Bulk creating remaining ServerStaging entries...")
            ServerStaging.objects.bulk_create(staging_objs)

        write_log(f"[{datetime.datetime.now()}] All ServerStaging entries created.")
        return True, "ServerStaging creation successful", index

    except Exception as e:
        msg = f"Error during ServerStaging creation: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg, index


def fill_summarytable():

    try:
        write_log(f"[{datetime.datetime.now()}] Analyzing and creating ServerGroupSummaryStaging entries...")

        # Process ServerStaging entries in chunks
        server_staging_qs = ServerStaging.objects.all().order_by('SERVER_ID')
        chunk_size = 50000
        existing_server_ids = set(ServerGroupSummaryStaging.objects.values_list('SERVER_ID', flat=True))
        new_summaries = []
        updated_summaries = []
        servers = []

        for server in server_staging_qs.iterator():
            servers.append(server)

            if len(servers) == chunk_size:
                hostname_groups = defaultdict(list)
                for server in servers:
                    hostname_groups[server.SERVER_ID].append(server)
                for SERVER_ID, server_list in hostname_groups.items():
                    field_analysis = analyze_server_fields(server_list)
                    if SERVER_ID in existing_server_ids:
                        # If it exists, update the existing summary
                        summary = ServerGroupSummaryStaging.objects.get(SERVER_ID=SERVER_ID)
                        summary.total_instances = len(server_list)
                        summary.constant_fields = field_analysis['constant']
                        summary.variable_fields = field_analysis['variable']
                        updated_summaries.append(summary)
                    else:
                        # If it doesn't exist, create a new summary
                        summary = ServerGroupSummaryStaging(
                            SERVER_ID=SERVER_ID,
                            total_instances=len(server_list),
                            constant_fields=field_analysis['constant'],
                            variable_fields=field_analysis['variable'],
                        )
                        new_summaries.append(summary)

                # Update the existing ServerGroupSummaryStaging objects in bulk
                if updated_summaries:
                    write_log(f"[{datetime.datetime.now()}] Bulk creating updated {len(updated_summaries)} ServerGroupSummaryStaging entries...")
                    ServerGroupSummaryStaging.objects.bulk_update(updated_summaries, ['total_instances', 'constant_fields', 'variable_fields'])

                # Create the new ServerGroupSummaryStaging objects in bulk
                if new_summaries:
                    write_log(f"[{datetime.datetime.now()}] Bulk creating new {len(new_summaries)} ServerGroupSummaryStaging entries...")
                    ServerGroupSummaryStaging.objects.bulk_create(new_summaries)
                    existing_server_ids.update(s.SERVER_ID for s in new_summaries)

                servers = []
                new_summaries = []
                updated_summaries = []
                #existing_server_ids.update(s.SERVER_ID for s in new_summaries)

        # Process the remaining servers
        if servers:
            hostname_groups = defaultdict(list)
            for server in servers:
                hostname_groups[server.SERVER_ID].append(server)
            for SERVER_ID, server_list in hostname_groups.items():
                field_analysis = analyze_server_fields(server_list)
                if SERVER_ID in existing_server_ids:
                    # If it exists, update the existing summary
                    summary = ServerGroupSummaryStaging.objects.get(SERVER_ID=SERVER_ID)
                    summary.total_instances = len(server_list)
                    summary.constant_fields = field_analysis['constant']
                    summary.variable_fields = field_analysis['variable']
                    updated_summaries.append(summary)
                else:
                    # If it doesn't exist, create a new summary
                    summary = ServerGroupSummaryStaging(
                        SERVER_ID=SERVER_ID,
                        total_instances=len(server_list),
                        constant_fields=field_analysis['constant'],
                        variable_fields=field_analysis['variable'],
                    )
                    new_summaries.append(summary)
            # Update the existing ServerGroupSummaryStaging objects in bulk
            
            if updated_summaries:
                write_log(f"[{datetime.datetime.now()}] Bulk creating remaining updated {len(updated_summaries)} ServerGroupSummaryStaging entries...")
                ServerGroupSummaryStaging.objects.bulk_update(updated_summaries, ['total_instances', 'constant_fields', 'variable_fields'])
            # Create the new ServerGroupSummaryStaging objects in bulk
            if new_summaries:
                write_log(f"[{datetime.datetime.now()}] Bulk creating remaining new {len(new_summaries)} ServerGroupSummaryStaging entries...")
                ServerGroupSummaryStaging.objects.bulk_create(new_summaries)

        return True, "ServerGroupSummaryStaging import successful"

    except Exception as e:
        msg = f"Error during ServerGroupSummaryStaging import: {e}"
        ImportStatus.objects.create(success=False, message=msg)
        write_log(f"[{datetime.datetime.now()}] {msg}")
        return False, msg


def swap_tables(start_time, entries_created, summary_count):
    try:
        write_log(f"[{datetime.datetime.now()}] Swapping ServerStaging -> Server / ServerGroupSummaryStaging -> ServerGroupSummary")
        with django_connection.cursor() as cursor:
            cursor.execute("BEGIN;")
            print(f"[{datetime.datetime.now()}] DROP inventory_serverbackup")
            cursor.execute("DROP TABLE IF EXISTS inventory_serverbackup;")
            print(f"[{datetime.datetime.now()}] RENAME inventory_server to inventory_serverbackup")
            cursor.execute("ALTER TABLE inventory_server RENAME TO inventory_serverbackup;")
            print(f"[{datetime.datetime.now()}] RENAME inventory_serverstaging to inventory_server")
            cursor.execute("ALTER TABLE inventory_serverstaging RENAME TO inventory_server;")
            print(f"[{datetime.datetime.now()}] DROP inventory_servergroupsummarybackup")
            cursor.execute("DROP TABLE IF EXISTS inventory_servergroupsummarybackup;")
            print(f"[{datetime.datetime.now()}] RENAME inventory_servergroupsummary to inventory_servergroupsummarybackup")
            cursor.execute("ALTER TABLE inventory_servergroupsummary RENAME TO inventory_servergroupsummarybackup;")
            print(f"[{datetime.datetime.now()}] RENAME inventory_servergroupsummarystaging to inventory_servergroupsummary")
            cursor.execute("ALTER TABLE inventory_servergroupsummarystaging RENAME TO inventory_servergroupsummary;")
            print(f"[{datetime.datetime.now()}] COMMIT")
            cursor.execute("COMMIT;")

        end_time = datetime.datetime.now()
        total_duration = end_time - start_time
        msg = f"Import successful: {entries_created} entries imported, {summary_count} servers grouped created"
        ImportStatus.objects.create(success=True, message=msg, nb_entries_created=entries_created, nb_groups_created=summary_count)
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


def import_from_csv_file(verbose=True):
    start_time = datetime.datetime.now()

    # DPR import
    if getattr(settings, 'ENVIRONMENT', 'PROD') != 'DEV':
        for name, url in DPR_URL.items():
            success, message = get_DPR_data(name, url)
            if success == False:
                return False, message

    # Fix the data    
    for name, csvpath in DPR_FILE_PATH_CSV.items():   
        fix_DPR_data(name, csvpath)

    # Compare the Delta
    write_log(f"[{start_time}] Check the delta...")
    old_count = Server.objects.count()
    new_count=count_all_csv()

    if old_count > 0:
        variation = abs(new_count - old_count) / old_count
        if variation > VARIATION_ALLOWED:
            msg = f"Variation too big ({variation:.2%}), import cancelled"
            ImportStatus.objects.create(success=False, message=msg, nb_entries_created=0)
            write_log(f"[{datetime.datetime.now()}] {msg}")
            return False, msg
        else:
            write_log(f"[{datetime.datetime.now()}] Nb of servers: Current: {old_count}, New: {new_count}")
    
    write_log(f"[{datetime.datetime.now()}] Recreate the databases...")
    recreate_staging_table()
    
    entries_created = 0
    for name, csvpath in DPR_FILE_PATH_CSV.items():   
        success, message, nb_entries = fill_table(name, csvpath)
        if success == False:
            return False, message
        entries_created = entries_created + nb_entries
            
    success, message = fill_summarytable()
    if success == False:
        return False, message
    
    summary_count = ServerGroupSummaryStaging.objects.count()
    print(f'[{datetime.datetime.now()}] Created {summary_count} summaries with full field analysis')            

    success, message = swap_tables(start_time, entries_created, summary_count)
    return success, message
