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


def _get_cell_value(item, col, annotations_dict):
    if col == 'ANNOTATION':
        ann = annotations_dict.get(getattr(item, 'ID', ''))
        return clean_value(ann.comment if ann else '')
    return clean_value(getattr(item, col, ''))


def generate_excel(filepath, items, annotations_dict, columns):
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"

    first_column = 'ID'
    columns = [col for col in columns if col != first_column]
    columns = [first_column] + columns

    ws.append(columns)
    for item in items:
        ws.append([_get_cell_value(item, col, annotations_dict) for col in columns])

    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)


def generate_csv(filepath, items, annotations_dict, columns):
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, delimiter=';')

        first_column = 'ID'
        columns = [col for col in columns if col != first_column]
        columns = [first_column] + columns

        writer.writerow(columns)
        for item in items:
            writer.writerow([_get_cell_value(item, col, annotations_dict) for col in columns])

    os.replace(temp_filepath, filepath)
