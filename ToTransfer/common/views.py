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


@login_required
def generate_charts(request, server_data, json_data, selected_fields, chart_types, field_totals, hidden_filter_values=None, default_keyfield='SERVER_ID'):
    # hidden_filter_values: dict {param_name: set_of_lowercase_values} — hides only specific param=value combos
    
    permanent_filter_selection = request.GET.get('permanentfilter')
    hidden_filter_values = hidden_filter_values or {}
    
    filter_text = ""
    filter_parts = []
    
    for key, value in request.GET.items():
        if not value.strip():
            continue
        # Skip only the specific param=value combos that are flagged as hidden
        if key in hidden_filter_values and value.lower() in hidden_filter_values[key]:
            continue
        # days_open: URL param name differs from inputname in field_labels ('daysopen')
        if key == 'days_open' and value.strip().isdigit() and int(value) > 0:
            filter_parts.append(f"Days Open: ≥ {value}d")
            continue
        for field_info in json_data['fields'].values():
            if 'inputname' not in field_info:
                continue
            input_name = field_info['inputname']
            if field_info.get('fieldtype') == 'date':
                if key == f'{input_name}_from':
                    filter_parts.append(f"{field_info['displayname']} ≥ {value}")
                    break
                if key == f'{input_name}_to':
                    filter_parts.append(f"{field_info['displayname']} ≤ {value}")
                    break
            elif input_name == key:
                filter_parts.append(f"{field_info['displayname']}: {value}")
                break

    if permanent_filter_selection:
        filter_parts.append(permanent_filter_selection)

    filter_text = ", ".join(filter_parts)  # kept for PDF export
    
    # Total unique servers
    total_unique_servers = len(set(s[default_keyfield] for s in server_data))
    
    charts_data = []
    
    for field_key, chart_type in zip(selected_fields, chart_types):
        if field_key and chart_type:
            field_info = json_data.get('fields', {}).get(field_key)
            if not field_info:
                continue
            
            display_name = field_info['displayname']
            
            alias_map = {
                'priority_asset': 'server_unique__priority_asset',
                'in_live_play': 'server_unique__in_live_play',
                'action_during_lp': 'server_unique__action_during_lp',
                'original_action_during_lp': 'server_unique__original_action_during_lp',
                'cluster': 'server_unique__cluster',
                'cluster_type': 'server_unique__cluster_type',
                #'ANNOTATION': 'ANNOTATION'
            }
            
            data_field = alias_map.get(field_key, field_key)
           
            
            # Count all occurrences (no deduplication)
            unique_combinations = set()
            for server in server_data:
                server_id = server.get(default_keyfield)
                value = server.get(data_field, 'Unknown')
                if value is None or value == '':
                    value = 'Unknown'
                
                unique_combinations.add((server_id, str(value)))
            
            value_counts = {}
            for server_id, value in unique_combinations:
                value_counts[value] = value_counts.get(value, 0) + 1
            
            field_total_count = field_totals.get(field_key, len(unique_combinations))
            
            # Sort and take top 19
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
        'filter_text': filter_text,
        'filter_parts': filter_parts,
    }
    
    return render(request, 'common/charts.html', context)
