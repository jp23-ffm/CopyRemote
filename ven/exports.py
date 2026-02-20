import csv
import os

from django.conf import settings
from openpyxl import Workbook

EXPORT_DIR = os.path.join(settings.MEDIA_ROOT, 'exports')

VIRTUAL_FIELDS = {'days_open', 'ANNOTATION'}


def clean_value(value):
    if value is None:
        return ''
    text = str(value)
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    return text


def _get_cell_value(server, col, annotations_dict, days_open_dict):
    if col == 'days_open':
        return days_open_dict.get(server.SERVER_ID, '')
    if col == 'ANNOTATION':
        ann = annotations_dict.get(server.SERVER_ID)
        return clean_value(ann.comment if ann else '')
    return clean_value(getattr(server, col, ''))


def generate_excel(filepath, servers, annotations_dict, days_open_dict, columns):
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Servers"

    first_column = "SERVER_ID"
    columns = [col for col in columns if col != first_column]
    columns = [first_column] + columns

    ws.append(columns)

    for server in servers:
        ws.append([_get_cell_value(server, col, annotations_dict, days_open_dict) for col in columns])

    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)


def generate_csv(filepath, servers, annotations_dict, days_open_dict, columns):
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        first_column = "SERVER_ID"
        columns = [col for col in columns if col != first_column]
        columns = [first_column] + columns

        writer.writerow(columns)

        for server in servers:
            writer.writerow([_get_cell_value(server, col, annotations_dict, days_open_dict) for col in columns])

    os.replace(temp_filepath, filepath)
