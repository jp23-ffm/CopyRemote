import csv
import os

from django.conf import settings
from openpyxl import Workbook

EXPORT_DIR = os.path.join(settings.MEDIA_ROOT, 'exports')

VIRTUAL_FIELDS = {'ANNOTATION'}


def clean_value(value):
    if value is None:
        return ''
    text = str(value)
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    return text


def _get_cell_value(server, col, annotations_dict):
    if col == 'ANNOTATION':
        ann = annotations_dict.get(server.SERIAL)
        return clean_value(ann.comment if ann else '')
    return clean_value(getattr(server, col, ''))


def generate_excel(filepath, servers, annotations_dict, columns):
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Servers"

    ws.append(columns)

    for server in servers:
        ws.append([_get_cell_value(server, col, annotations_dict) for col in columns])

    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)


def generate_csv(filepath, servers, annotations_dict, columns):
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        writer.writerow(columns)

        for server in servers:
            writer.writerow([_get_cell_value(server, col, annotations_dict) for col in columns])

    os.replace(temp_filepath, filepath)
