# views.py

@login_required
def list_saved_charts(request):
    """Lister les vues sauvegardées"""
    try:
        # Vérifier que le UserProfile existe
        try:
            user_profile = request.user.userprofile
        except UserProfile.DoesNotExist:
            # Pas de profil = retourner liste vide
            return JsonResponse({
                'success': True,
                'charts': []
            })
        
        # Récupérer les charts
        charts = SavedChart.objects.filter(user_profile=user_profile).values('id', 'name', 'filters')
        
        return JsonResponse({
            'success': True,
            'charts': list(charts)  # list() pour convertir le QuerySet
        })
        
    except Exception as e:
        print(f"Error in list_saved_charts: {e}")  # Debug
        return JsonResponse({
            'success': False,
            'error': str(e),
            'charts': []  # Retourner liste vide même en cas d'erreur
        }, status=500)
