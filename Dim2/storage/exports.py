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


def _get_cell_value(item, col, annotations_dict, annotation_key=None):
    if col == 'ANNOTATION':
        key = annotation_key if annotation_key is not None else getattr(item, 'ID', '')
        ann = annotations_dict.get(key)
        return clean_value(ann.comment if ann else '')
    return clean_value(getattr(item, col, ''))


def generate_excel(filepath, items, annotations_dict, columns, annotation_key_fn=None):
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"

    first_column = 'ID'
    columns = [col for col in columns if col != first_column]
    columns = [first_column] + columns

    ws.append(columns)
    for item in items:
        key = annotation_key_fn(item) if annotation_key_fn else None
        ws.append([_get_cell_value(item, col, annotations_dict, key) for col in columns])

    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)


def generate_csv(filepath, items, annotations_dict, columns, annotation_key_fn=None):
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, delimiter=';')

        first_column = 'ID'
        columns = [col for col in columns if col != first_column]
        columns = [first_column] + columns

        writer.writerow(columns)
        for item in items:
            key = annotation_key_fn(item) if annotation_key_fn else None
            writer.writerow([_get_cell_value(item, col, annotations_dict, key) for col in columns])

    os.replace(temp_filepath, filepath)
