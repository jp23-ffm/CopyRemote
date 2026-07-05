import csv
import os

from django.conf import settings
from openpyxl import Workbook

EXPORT_DIR = os.path.join(settings.MEDIA_ROOT, 'exports')


def clean_value(value):
    if value is None:
        return ''
    text = str(value)
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    return text


def _get_cell_value(application, col):
    return clean_value(getattr(application, col, ''))


def generate_excel(filepath, applications, columns):
    temp_filepath = filepath + '.tmp'
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"

    ws.append(columns)

    for application in applications:
        ws.append([_get_cell_value(application, col) for col in columns])

    wb.save(temp_filepath)
    os.replace(temp_filepath, filepath)


def generate_csv(filepath, applications, columns):
    temp_filepath = filepath + '.tmp'
    with open(temp_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        writer.writerow(columns)

        for application in applications:
            writer.writerow([_get_cell_value(application, col) for col in columns])

    os.replace(temp_filepath, filepath)
