import csv
import os

from django.conf import settings
from openpyxl import Workbook

# Define the directory where exports will be stored
EXPORT_DIR = os.path.join(settings.MEDIA_ROOT, 'exports')


# Function to recursively get a nested attribute using a string path
def get_db_attr(obj, attr):

    parts = attr.split('.')
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None
    return obj


# Function to generate an Excel file from a list of servers
def generate_excel(filepath, servers, annotations_dict, columns, FILTER_MAPPING, exportnotes, su_dict=None, su_fields=None):

    su_fields = su_fields or set()
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Servers"

    first_column = "SERVER_ID"  # Define SERVER_ID as first column
    columns = [col for col in columns if col != first_column]  # Avoid having SERVER_ID repeated twice
    columns = [first_column] + columns

    if exportnotes:
        ws.append(columns + ["NOTES"])  # Write the header row with the field Notes
    else:
        ws.append(columns)  # Write the header row

    if servers.exists():
        for server in servers:
            row = []
            first_value = get_db_attr(server, FILTER_MAPPING[first_column])  # Add the value for the first column
            row.append(first_value)
            for col in columns[1:]:  # Skip the first column
                if col in su_fields:
                    su = su_dict.get(server.SERVER_ID) if su_dict else None
                    value = getattr(su, col, '') if su else ''
                else:
                    value = get_db_attr(server, FILTER_MAPPING[col])
                row.append(value)
                
            if exportnotes:
                # Add annotation data
                annotation = annotations_dict.get(server.SERVER_ID)
                if annotation:
                    row.append(clean_value(annotation.notes or ''))
                else:
                    row.extend([''])
                
            ws.append(row)
    else:
        print("No servers matching the applied filters were found.")

    # Save the workbook and replace the original file
    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)
        

# Function to generate a CSV file from a list of servers        
def generate_csv(filepath, servers, annotations_dict, columns, FILTER_MAPPING, exportnotes, su_dict=None, su_fields=None):

    su_fields = su_fields or set()
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        first_column = "SERVER_ID"  # Define SERVER_ID as first column
        columns = [col for col in columns if col != first_column]  # Avoid having SERVER_ID repeated twice
        columns = [first_column] + columns

        if exportnotes:
            writer.writerow(columns + ["NOTES"])  # Write the header row with the field Notes
        else:
            writer.writerow(columns)  # Write the header row

        # Write the data rows
        for server in servers:
            first_value = get_db_attr(server, FILTER_MAPPING[first_column])  # Add the value for the first column
            data_row = [first_value]
            for col in columns[1:]:
                if col in su_fields:
                    su = su_dict.get(server.SERVER_ID) if su_dict else None
                    data_row.append(getattr(su, col, '') if su else '')
                else:
                    data_row.append(get_db_attr(server, FILTER_MAPPING[col]))
            
            if exportnotes:
                # Add annotation data
                annotation = annotations_dict.get(server.SERVER_ID)
                if annotation:
                    data_row = data_row + [clean_value(annotation.notes or '')]
                else:
                    data_row = data_row + ['']
                
            writer.writerow(data_row)

    # Replace the original file with the temporary file
    os.replace(temp_filepath, filepath)
    

def clean_value(value):

    # Remove line breaks and return clean string
    
    if value is None:
        return ''
    text = str(value)
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    return text

    
def generate_csv_grouped(filepath, hostnames, server_groups, summaries_dict, annotations_dict, columns, exportnotes, su_dict=None, su_fields=None):

    su_fields = su_fields or set()
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        first_column = "SERVER_ID"  # Define SERVER_ID as first column
        columns = [col for col in columns if col != first_column]  # Avoid having SERVER_ID repeated twice
        columns = [first_column] + columns

        if exportnotes:
            writer.writerow(columns + ["NOTES"])  # Write the header row with the Notes field
        else:
            writer.writerow(columns)  # Write the header row

        for hostname_item in hostnames:
            hostname = hostname_item['SERVER_ID']
            server_list = server_groups.get(hostname, [])

            if not server_list:
                continue

            summary = summaries_dict.get(hostname)
            annotation = annotations_dict.get(hostname)
            row = []

            # If only one visible instance, show its real values
            if len(server_list) == 1:
                single_server = server_list[0]
                for field_name in columns:
                    if field_name in su_fields:
                        su = su_dict.get(hostname) if su_dict else None
                        value = getattr(su, field_name, '') if su else ''
                    else:
                        value = getattr(single_server, field_name, '')
                    row.append(clean_value(value))
            else:
                # Multiple instances: use summary data
                if summary:
                    for field_name in columns:
                        if field_name in su_fields:
                            su = su_dict.get(hostname) if su_dict else None
                            value = getattr(su, field_name, '') if su else ''
                            row.append(clean_value(value))
                        # Check if constant field
                        elif field_name in summary.constant_fields:
                            row.append(clean_value(summary.constant_fields[field_name]))
                        # Check if variable field
                        elif field_name in summary.variable_fields:
                            # Show preview of variable values
                            preview = summary.variable_fields[field_name].get('preview', '')
                            row.append(clean_value(preview))
                        else:
                            row.append('')
                else:
                    # No summary available
                    row.extend([''] * len(columns))
            
            # Add annotation data
            if exportnotes:
                if annotation:
                    row.append(clean_value(annotation.notes or ''))
                else:
                    row.extend([''])
            
            writer.writerow(row)                                

    # Replace the original file with the temporary file
    os.replace(temp_filepath, filepath)


def generate_excel_grouped(filepath, hostnames, server_groups, summaries_dict, annotations_dict, columns, exportnotes, su_dict=None, su_fields=None):

    su_fields = su_fields or set()
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Servers"

    first_column = "SERVER_ID"  # Define SERVER_ID as first column
    columns = [col for col in columns if col != first_column]  # Avoid having SERVER_ID repeated twice
    columns = [first_column] + columns

    if exportnotes:
        ws.append(columns + ["NOTES"])  # Write the header row with the Notes field
    else:
        ws.append(columns)  # Write the header row

    for hostname_item in hostnames:
        hostname = hostname_item['SERVER_ID']
        server_list = server_groups.get(hostname, [])

        if not server_list:
            continue

        summary = summaries_dict.get(hostname)
        annotation = annotations_dict.get(hostname)
        row = []

        # If only one visible instance, show its real values
        if len(server_list) == 1:
            single_server = server_list[0]
            for field_name in columns:
                if field_name in su_fields:
                    su = su_dict.get(hostname) if su_dict else None
                    value = getattr(su, field_name, '') if su else ''
                else:
                    value = getattr(single_server, field_name, '')
                row.append(clean_value(value))
        else:
            # Multiple instances: use summary data
            if summary:
                for field_name in columns:
                    if field_name in su_fields:
                        su = su_dict.get(hostname) if su_dict else None
                        value = getattr(su, field_name, '') if su else ''
                        row.append(clean_value(value))
                    # Check if constant field
                    elif field_name in summary.constant_fields:
                        row.append(clean_value(summary.constant_fields[field_name]))
                    # Check if variable field
                    elif field_name in summary.variable_fields:
                        # Show preview of variable values
                        preview = summary.variable_fields[field_name].get('preview', '')
                        row.append(clean_value(preview))
                    else:
                        row.append('')
            else:
                # No summary available
                row.extend([''] * len(columns))
            
        if exportnotes:
            # Add annotation data
            if annotation:
                row.append(clean_value(annotation.notes or ''))
            else:
                row.extend([''])
                            
        ws.append(row)

    # Replace the original file with the temporary file
    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)

