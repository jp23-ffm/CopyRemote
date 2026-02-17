from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.db.models import Count
import json
import os
from django.conf import settings

from userapp.models import SavedChart


@login_required
@require_POST
def save_chart_view(request):

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        filters = data.get('filters', {})
        app_name = data.get('app_name', 'inventory')  # get  the app
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
        
        user_profile = request.user.userprofile
        
        # Create or update
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
        print(f"Error saving chart: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def list_saved_charts(request):
    try:
        app_name = request.GET.get('app', 'inventory')  # Get the app
        
        if not hasattr(request.user, 'userprofile'):
            return JsonResponse({'success': True, 'charts': []})
        
        user_profile = request.user.userprofile
        
        # Filtrer par user ET par app
        charts = SavedChart.objects.filter(
            user_profile=user_profile,
            app_name=app_name  # Filter by app
        ).values('id', 'name', 'filters')
        
        return JsonResponse({
            'success': True,
            'charts': list(charts)
        })
        
    except Exception as e:
        print(f"Error listing charts: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e),
            'charts': []
        }, status=500)


@login_required
@require_POST
def delete_saved_chart(request, chart_id):
    try:
        user_profile = request.user.userprofile
        chart = SavedChart.objects.get(id=chart_id, user_profile=user_profile)
        chart_name = chart.name
        chart.delete()
        
        return JsonResponse({
            'success': True,
            'message': f"Chart view '{chart_name}' deleted"
        })
    except SavedChart.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Chart not found'}, status=404)
    except Exception as e:
        print(f"Error deleting chart: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

"""
@login_required
def generate_charts(request, servers, json_data):

    selected_fields = request.GET.getlist('fields')  # Ex: ['SERVER_ID', 'APP_NAME_VALUE']
    chart_types = request.GET.getlist('types')       # Ex: ['bar', 'pie']
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    filter_text=""
    filter_parts = [] 
    print(servers)
    
    # Retrieve the filters based on the url
    for key, value in request.GET.items():
        for field_key, field_info in json_data['fields'].items():
            if 'inputname' in field_info and field_info['inputname']==key:
                fragment = f"{field_info['displayname']}: {value}"
                filter_parts.append(fragment)

    filter_parts.append(permanent_filter_selection)
    filter_text = ", ".join(filter_parts)
 
    # Generate the data for each chart
    charts_data = []
    
    for field_key, chart_type in zip(selected_fields, chart_types):
        if field_key and chart_type:
            field_info = json_data.get('fields', {}).get(field_key)
            if not field_info:
                continue

            display_name = field_info['displayname']  # ex: "Application Name"
                
            alias_map = {
                'priority_asset': 'server_unique__priority_asset',
                'in_live_play': 'server_unique__in_live_play',
                'action_during_lp': 'server_unique__action_during_lp',
                'original_action_during_lp': 'server_unique__original_action_during_lp',
                'cluster': 'server_unique__cluster',
                'cluster_type': 'server_unique__cluster_type',
                "ANNOTATION": "notes"
            }     
            field_key = alias_map.get(field_key, field_key)       
                
            # Chart aggregation (top 20 - 19 + others)
            
            aggregated_chart = (
                servers
                .values(field_key)
                .annotate(count=Count('SERVER_ID', distinct=True))
                .order_by('-count')
                [:19]
            )
            
            # Table aggregation (top 100)
            aggregated_table = (
                servers
                .values(field_key)
                .annotate(count=Count('SERVER_ID', distinct=True))
                .order_by('-count')
                [:100]
            )

            # Calculate "Others" for chart
            total_in_chart = sum(item['count'] for item in aggregated_chart)
            total_servers = servers.count()
            others_count_chart = total_servers - total_in_chart

            # Calculate "Others" for table
            total_in_table = sum(item['count'] for item in aggregated_table)
            others_count_table = total_servers - total_in_table
                        
            # Labels and values for the chart
            chart_labels = [str(item[field_key]) if item[field_key] else 'Unknown' for item in aggregated_chart]
            chart_values = [item['count'] for item in aggregated_chart]
            
            if others_count_chart > 0:
                chart_labels.append('Others')
                chart_values.append(others_count_chart)
            
            # Labels and values for the table
            table_labels = [str(item[field_key]) if item[field_key] else 'Unknown' for item in aggregated_table]
            table_values = [item['count'] for item in aggregated_table]
            
            if others_count_table > 0:
                table_labels.append('Others')
                table_values.append(others_count_table)
            
            charts_data.append({
                'field': display_name,
                'type': chart_type,
                'labels': chart_labels,
                'values': chart_values,
                'table_labels': table_labels,
                'table_values': table_values,
                'different_values': aggregated_table.count(),
                'total': total_servers,
            })
    
    context = {
        'charts_data': json.dumps(charts_data),
        'total_servers': servers.count(),
        'filter_text': filter_text 
    }

    
    return render(request, f'common/charts.html', context)
"""

@login_required
def generate_charts(request, server_data, json_data, selected_fields, chart_types, field_totals):
    """
    Génère les charts à partir des données
    """
    
    permanent_filter_selection = request.GET.get('permanentfilter')
    
    filter_text = ""
    filter_parts = []
    
    for key, value in request.GET.items():
        for field_key, field_info in json_data['fields'].items():
            if 'inputname' in field_info and field_info['inputname'] == key:
                fragment = f"{field_info['displayname']}: {value}"
                filter_parts.append(fragment)
    
    filter_parts.append(permanent_filter_selection)
    filter_text = ", ".join(filter_parts)
    
    # Total unique servers
    total_unique_servers = len(set(s['SERVER_ID'] for s in server_data))
    
    charts_data = []
    
    for field_key, chart_type in zip(selected_fields, chart_types):
        if field_key and chart_type:
            field_info = json_data.get('fields', {}).get(field_key)
            if not field_info:
                continue
            
            display_name = field_info['displayname']

            # Values are already enriched in server_data under field_key
            data_field = field_key
            
            # Compter TOUTES les occurrences (pas de déduplication par SERVER_ID)
            # On garde les combinaisons uniques (SERVER_ID, valeur)
            unique_combinations = set()
            for server in server_data:
                server_id = server.get('SERVER_ID')
                value = server.get(data_field, 'Unknown')
                if value is None or value == '':
                    value = 'Unknown'
                
                # Ajouter la combinaison unique
                unique_combinations.add((server_id, str(value)))
            
            # Maintenant compter par valeur (sans se soucier du SERVER_ID)
            value_counts = {}
            for server_id, value in unique_combinations:
                value_counts[value] = value_counts.get(value, 0) + 1
            
            # Utiliser le total pré-calculé
            field_total_count = field_totals.get(field_key, len(unique_combinations))
            
            # Trier et prendre le top 19 (pas top 1 !)
            sorted_items = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)[:19]
            
            top_values_count = sum(count for _, count in sorted_items)
            others_count = field_total_count - top_values_count
            
            chart_labels = [str(value) for value, _ in sorted_items]
            chart_values = [count for _, count in sorted_items]
            
            if others_count > 0:
                chart_labels.append('Others')
                chart_values.append(others_count)
            
            # Table (top 100)
            sorted_items_table = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)[:100]
            table_labels = [str(value) for value, _ in sorted_items_table]
            table_values = [count for _, count in sorted_items_table]
            
            top_table_count = sum(table_values)
            others_count_table = field_total_count - top_table_count
            
            if others_count_table > 0:
                table_labels.append('Others')
                table_values.append(others_count_table)
            
            charts_data.append({
                'field': display_name,
                'type': chart_type,
                'labels': chart_labels,
                'values': chart_values,
                'table_labels': table_labels,
                'table_values': table_values,
                'different_values': len(value_counts),
                'total': field_total_count,
            })
    
    context = {
        'charts_data': json.dumps(charts_data),
        'total_servers': total_unique_servers,
        'filter_text': filter_text
    }
    
    return render(request, 'common/charts.html', context)
