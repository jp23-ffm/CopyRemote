import csv
import datetime
import json
import os
import sys

from businesscontinuity.models import Server, ServerUnique
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

export_pathname="/tmp"
export_filename="businesscontinuity_servers_export"
LOG_PATH="/data/DPR_DATA/logs/businesscontinuity_servers_export.log"


def write_log(message):
    print(message)
    with open(LOG_PATH, 'a') as log_file:
        log_file.write(message + '\n')


def export_to_xlsx(servers, file_path):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Servers Data'

    headers = [
        'SERVER_ID', 'ITCONTINUITY_LEVEL', 'DAP_NAME', 'DAP_AUID', 'DATACENTER', 'TECH_FAMILY', 'MACHINE_TYPE', 'VM_TYPE', 'AFFINITY', 'DATABASE_TECHNO', 'DATABASE_DB_CI', 'VITAL_LEVEL',
        'SUPPORT_GROUP', 'APPLICATION_SUPPORT_GROUP', 'IT_CLUSTER', 'COUNTRY', 'priority_asset', 'in_live_play', 'action_during_lp', 'annotation', 'cluster', 'cluster_type', 'bc_exception'
    ]

    ws.append(headers)

    for server in servers:
        server_unique = server.server_unique
        data = [
            server.SERVER_ID, server.ITCONTINUITY_LEVEL, server.DAP_NAME, server.DAP_AUID, server.DATACENTER, server.TECH_FAMILY, server.MACHINE_TYPE, server.VM_TYPE, 
            server.AFFINITY, server.DATABASE_TECHNO, server.DATABASE_DB_CI, server.VITAL_LEVEL, server.SUPPORT_GROUP, server.APPLICATION_SUPPORT_GROUP, server.IT_CLUSTER, server.COUNTRY, 
            server_unique.priority_asset, server_unique.in_live_play, server_unique.action_during_lp, server_unique.annotation, server_unique.cluster, server_unique.cluster_type, server_unique.bc_exception
        ]
        ws.append(data)

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    wb.save(file_path)


def export_to_csv(servers, file_path):
    data = []
    for server in servers:
        server_unique = server.server_unique
        data.append({
            'SERVER_ID': server.SERVER_ID,
            'ITCONTINUITY_LEVEL': server.ITCONTINUITY_LEVEL,
            'DAP_NAME': server.DAP_NAME,
            'DAP_AUID': server.DAP_AUID,
            'DATACENTER': server.DATACENTER,
            'TECH_FAMILY': server.TECH_FAMILY,
            'MACHINE_TYPE': server.MACHINE_TYPE,
            'VM_TYPE': server.VM_TYPE,
            'AFFINITY': server.AFFINITY,
            'DATABASE_TECHNO': server.DATABASE_TECHNO,
            'DATABASE_DB_CI': server.DATABASE_DB_CI,
            'VITAL_LEVEL': server.VITAL_LEVEL,
            'SUPPORT_GROUP': server.SUPPORT_GROUP,
            'APPLICATION_SUPPORT_GROUP': server.APPLICATION_SUPPORT_GROUP,
            'IT_CLUSTER': server.IT_CLUSTER,
            'COUNTRY': server.COUNTRY,
            'priority_asset': server_unique.priority_asset,
            'in_live_play': server_unique.in_live_play,
            'action_during_lp': server_unique.action_during_lp,
            'annotation': server_unique.annotation,
            'cluster': server_unique.cluster,
            'cluster_type': server_unique.cluster_type,
            'bc_exception': server_unique.bc_exception
        })

    # Write data to CSV file
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys(), delimiter=';')
        writer.writeheader()
        writer.writerows(data)


def export_to_json(servers, file_path):
    servers_list = []
    for server in servers:
        server_unique = server.server_unique
        data = {
            'SERVER_ID': server.SERVER_ID,
            'ITCONTINUITY_LEVEL': server.ITCONTINUITY_LEVEL,
            'DAP_NAME': server.DAP_NAME,
            'DAP_AUID': server.DAP_AUID,
            'DATACENTER': server.DATACENTER,
            'TECH_FAMILY': server.TECH_FAMILY,
            'MACHINE_TYPE': server.MACHINE_TYPE,
            'VM_TYPE': server.VM_TYPE,
            'AFFINITY': server.AFFINITY,
            'DATABASE_TECHNO': server.DATABASE_TECHNO,
            'DATABASE_DB_CI': server.DATABASE_DB_CI,
            'VITAL_LEVEL': server.VITAL_LEVEL,
            'SUPPORT_GROUP': server.SUPPORT_GROUP,
            'APPLICATION_SUPPORT_GROUP': server.APPLICATION_SUPPORT_GROUP,
            'IT_CLUSTER': server.IT_CLUSTER,
            'COUNTRY': server.COUNTRY,
            'priority_asset': server_unique.priority_asset,
            'in_live_play': server_unique.in_live_play,
            'action_during_lp': server_unique.action_during_lp,
            'annotation': server_unique.annotation,
            'cluster': server_unique.cluster,
            'cluster_type': server_unique.cluster_type,
            'bc_exception': server_unique.bc_exception
        }
        servers_list.append(data)

    with open(file_path, 'w', encoding='utf-8') as jsonfile:
        json.dump(servers_list, jsonfile, indent=4, ensure_ascii=False)


def export_businesscontinuity(format):
    write_log("----------------------------------------------------------")
    write_log(f"Started at {datetime.datetime.now()}")
    servers = Server.objects.all().select_related('server_unique').order_by('SERVER_ID')

    if not servers.exists():
        write_log("No servers matching the applied filters were found.")
        return False, "No servers matching the applied filters were found."

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    file_path = f'{export_pathname}/{export_filename}.{format}'

    if format == 'xlsx':
        export_to_xlsx(servers, file_path)
    elif format == 'csv':
        export_to_csv(servers, file_path)
    elif format == 'json':
        export_to_json(servers, file_path)

    write_log(f"Ended at {datetime.datetime.now()}")
    write_log(f'Saved {len(servers)} servers to {file_path}')
    return True, f'Saved {len(servers)} servers to {file_path}'


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ['xlsx', 'csv', 'json']:
        write_log('Invalid or missing export format argument.')
        sys.exit(1)
    export_businesscontinuity(sys.argv[1])
