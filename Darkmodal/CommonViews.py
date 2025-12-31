# common/views.py
from userapp.models import UserPreferences

@login_required
def get_preferences(request):
    """Récupérer les préférences pour une app"""
    try:
        app_name = request.GET.get('app', 'global')
        user_profile = request.user.userprofile
        
        # Récupérer ou créer les préférences
        preferences, created = UserPreferences.objects.get_or_create(
            user_profile=user_profile,
            app_name=app_name,
            defaults={'settings': {}}
        )
        
        return JsonResponse({
            'success': True,
            'settings': preferences.settings
        })
        
    except Exception as e:
        print(f"Error getting preferences: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'settings': {}
        }, status=500)


@login_required
@require_POST
def save_preferences(request):
    """Sauvegarder les préférences"""
    try:
        data = json.loads(request.body)
        app_name = data.get('app_name', 'global')
        settings = data.get('settings', {})
        
        user_profile = request.user.userprofile
        
        # Créer ou mettre à jour
        preferences, created = UserPreferences.objects.update_or_create(
            user_profile=user_profile,
            app_name=app_name,
            defaults={'settings': settings}
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Preferences saved'
        })
        
    except Exception as e:
        print(f"Error saving preferences: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def update_single_preference(request):
    """Mettre à jour UN setting spécifique (plus pratique pour dark mode)"""
    try:
        data = json.loads(request.body)
        app_name = data.get('app_name', 'global')
        key = data.get('key')  # Ex: 'theme'
        value = data.get('value')  # Ex: 'dark'
        
        if not key:
            return JsonResponse({'success': False, 'error': 'Key is required'}, status=400)
        
        user_profile = request.user.userprofile
        
        # Récupérer ou créer les préférences
        preferences, created = UserPreferences.objects.get_or_create(
            user_profile=user_profile,
            app_name=app_name,
            defaults={'settings': {}}
        )
        
        # Mettre à jour le setting spécifique
        preferences.set_setting(key, value)
        
        return JsonResponse({
            'success': True,
            'message': f'Setting {key} updated'
        })
        
    except Exception as e:
        print(f"Error updating preference: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
