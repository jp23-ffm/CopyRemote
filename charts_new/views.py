# views.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
import json

@login_required
@require_POST
def save_chart_query(request):
    """Sauvegarder une requête de graphiques"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        query_string = data.get('queryString', '').strip()
        
        if not name or not query_string:
            return JsonResponse({'success': False, 'error': 'Name and query are required'}, status=400)
        
        # Compter les graphiques et filtres
        params = dict(item.split('=') for item in query_string.split('&') if '=' in item)
        chart_count = len([v for k, v in params.items() if k == 'fields'])
        filters_count = len([k for k in params.keys() if k not in ['fields', 'types', 'page']])
        
        # Créer ou mettre à jour
        saved_query, created = SavedChartQuery.objects.update_or_create(
            user=request.user,
            name=name,
            defaults={
                'description': description,
                'query_string': query_string,
                'chart_count': chart_count,
                'filters_count': filters_count,
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': f"Query '{name}' saved successfully",
            'id': saved_query.id,
            'created': created
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def list_saved_queries(request):
    """Lister les requêtes sauvegardées de l'utilisateur"""
    queries = SavedChartQuery.objects.filter(user=request.user).values(
        'id', 'name', 'description', 'query_string', 
        'chart_count', 'filters_count', 'created_at', 'last_used', 'use_count'
    )
    
    return JsonResponse({
        'success': True,
        'queries': list(queries)
    })


@login_required
@require_POST
def delete_saved_query(request, query_id):
    """Supprimer une requête sauvegardée"""
    try:
        query = SavedChartQuery.objects.get(id=query_id, user=request.user)
        query_name = query.name
        query.delete()
        
        return JsonResponse({
            'success': True,
            'message': f"Query '{query_name}' deleted successfully"
        })
    except SavedChartQuery.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Query not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def load_saved_query(request, query_id):
    """Charger et rediriger vers une requête sauvegardée"""
    try:
        query = SavedChartQuery.objects.get(id=query_id, user=request.user)
        query.increment_usage()
        
        # Rediriger vers la page de charts avec la query string
        return redirect(f"/charts/?{query.query_string}")
    except SavedChartQuery.DoesNotExist:
        return HttpResponse("Query not found", status=404)