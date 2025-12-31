# common/views.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from userapp.models import SavedChart  # ← Import depuis userapp
import json

@login_required
@require_POST
def save_chart_view(request):
    """Sauvegarder une vue de graphiques"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        filters = data.get('filters', {})
        app_name = data.get('app_name', 'inventory')  # ← Récupérer l'app
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
        
        user_profile = request.user.userprofile
        
        # Créer ou mettre à jour
        saved_chart, created = SavedChart.objects.update_or_create(
            user_profile=user_profile,
            app_name=app_name,  # ← Utiliser app_name
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
    """Lister les vues sauvegardées pour une app spécifique"""
    try:
        app_name = request.GET.get('app', 'inventory')  # ← Récupérer l'app
        
        if not hasattr(request.user, 'userprofile'):
            return JsonResponse({'success': True, 'charts': []})
        
        user_profile = request.user.userprofile
        
        # Filtrer par user ET par app
        charts = SavedChart.objects.filter(
            user_profile=user_profile,
            app_name=app_name  # ← Filtrer par app
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
    """Supprimer une vue sauvegardée"""
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
