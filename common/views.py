# common/views.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.db.models import Count
import json
import os
from django.conf import settings

from .models import SavedChart


@login_required
@require_POST
def save_chart_view(request):
    """Sauvegarder une vue de graphiques - RÉUTILISABLE"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        filters = data.get('filters', {})
        app_name = data.get('app_name', 'inventory')  # ← Identifier l'app
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
        
        user_profile = request.user.userprofile
        
        saved_chart, created = SavedChart.objects.update_or_create(
            user_profile=user_profile,
            app_name=app_name,
            name=name,
            defaults={'filters': filters}
        )
        
        return JsonResponse({
            'success': True,
            'message': f"Chart view '{name}' saved successfully",
            'created': created
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def list_saved_charts(request):
    """Lister les vues sauvegardées - RÉUTILISABLE"""
    try:
        app_name = request.GET.get('app', 'inventory')  # ← Filtrer par app
        
        if not hasattr(request.user, 'userprofile'):
            return JsonResponse({'success': True, 'charts': []})
        
        user_profile = request.user.userprofile
        
        charts = SavedChart.objects.filter(
            user_profile=user_profile,
            app_name=app_name
        ).values('id', 'name', 'filters')
        
        return JsonResponse({
            'success': True,
            'charts': list(charts)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e), 'charts': []}, status=500)


@login_required
@require_POST
def delete_saved_chart(request, chart_id):
    """Supprimer une vue sauvegardée - RÉUTILISABLE"""
    try:
        user_profile = request.user.userprofile
        chart = SavedChart.objects.get(id=chart_id, user_profile=user_profile)
        chart_name = chart.name
        chart.delete()
        
        return JsonResponse({'success': True, 'message': f"Chart view '{chart_name}' deleted"})
    except SavedChart.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Chart not found'}, status=404)


def generic_chart_view(request, app_name, json_config_path, get_filtered_data_func):
    """
    Vue de graphiques GÉNÉRIQUE - réutilisable par toutes les apps
    
    Args:
        app_name: Nom de l'app ('inventory', 'businesscontinuity')
        json_config_path: Chemin vers le JSON de config
        get_filtered_data_func: Fonction pour filtrer les données
    """
    # Charger le JSON
    with open(json_config_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # Créer le mapping
    inputname_to_fieldkey = {}
    for field_key, field_info in json_data.get('fields', {}).items():
        if isinstance(field_info, dict) and 'inputname' in field_info:
            inputname_to_fieldkey[field_info['inputname']] = field_key
    
    # Récupérer les paramètres
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    
    # Construire requestfilters
    requestfilters = {}
    for key, value in request.GET.items():
        if key in ['fields', 'types', 'page']:
            continue
        if key in inputname_to_fieldkey:
            field_key = inputname_to_fieldkey[key]
            requestfilters[field_key] = value
    
    # Filtrer les données via la fonction fournie
    filtered_data = get_filtered_data_func(requestfilters, {})
    
    # Générer les charts
    charts_data = []
    
    for field_key, chart_type in zip(selected_fields, chart_types):
        if field_key and chart_type:
            field_info = json_data.get('chartable_fields', {}).get(field_key)
            if not field_info:
                continue
            
            model_field = field_info['inputname']
            display_name = field_info['displayname']
            
            # Agrégation
            aggregated_chart = (
                filtered_data
                .values(model_field)
                .annotate(count=Count('id'))
                .order_by('-count')
                [:20]
            )
            
            aggregated_table = (
                filtered_data
                .values(model_field)
                .annotate(count=Count('id'))
                .order_by('-count')
                [:100]
            )
            
            total_in_chart = sum(item['count'] for item in aggregated_chart)
            total_servers = filtered_data.count()
            others_count = total_servers - total_in_chart
            
            chart_labels = [str(item[model_field]) if item[model_field] else 'Unknown' for item in aggregated_chart]
            chart_values = [item['count'] for item in aggregated_chart]
            
            if others_count > 0:
                chart_labels.append('Others')
                chart_values.append(others_count)
            
            table_labels = [str(item[model_field]) if item[model_field] else 'Unknown' for item in aggregated_table]
            table_values = [item['count'] for item in aggregated_table]
            
            charts_data.append({
                'field': display_name,
                'type': chart_type,
                'labels': chart_labels,
                'values': chart_values,
                'table_labels': table_labels,
                'table_values': table_values,
                'total': total_servers,
            })
    
    context = {
        'charts_data': json.dumps(charts_data),
        'total_servers': filtered_data.count(),
        'app_name': app_name,
    }
    
    return render(request, 'common/charts.html', context)
