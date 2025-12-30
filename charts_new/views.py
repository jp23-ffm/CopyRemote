# views.py

@login_required
@require_POST
def save_chart_view(request):
    """Sauvegarder une vue de graphiques"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        filters = data.get('filters', {})  # Le JSON complet
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
        
        # Récupérer le UserProfile
        user_profile = request.user.userprofile
        
        # Créer ou mettre à jour
        saved_chart, created = SavedChart.objects.update_or_create(
            user_profile=user_profile,
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
    """Lister les vues sauvegardées"""
    user_profile = request.user.userprofile
    charts = SavedChart.objects.filter(user_profile=user_profile).values('id', 'name', 'filters')
    
    return JsonResponse({
        'success': True,
        'charts': list(charts)
    })


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

