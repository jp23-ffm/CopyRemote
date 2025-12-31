# inventory/views.py
from django.shortcuts import render
from common.views import generic_chart_view
from .models import Server
import os
from django.conf import settings

def get_filtered_servers(requestfilters, permanent_filter_selection):
    """Ta fonction existante"""
    # ... ton code
    pass

def chart_view(request):
    """Vue de charts pour inventory - utilise la vue générique"""
    json_path = os.path.join(settings.BASE_DIR, 'static', 'inventory_custom_filters.json')
    
    return generic_chart_view(
        request,
        app_name='inventory',
        json_config_path=json_path,
        get_filtered_data_func=get_filtered_servers
    )
