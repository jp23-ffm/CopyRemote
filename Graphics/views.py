# views.py
def chart_view(request):
    selected_fields = request.GET.getlist('fields')
    chart_types = request.GET.getlist('types')
    
    base_queryset = Server.objects.all()
    filtered_queryset = apply_filters_to_queryset(base_queryset, request)
    
    charts_data = []
    
    for field, chart_type in zip(selected_fields, chart_types):
        if field and chart_type:
            # Limite pour le graphique (top 20)
            chart_limit = 20
            
            # Récupérer TOP 20 pour le graphique
            aggregated_chart = (
                filtered_queryset
                .values(field)
                .annotate(count=Count('id'))
                .order_by('-count')
                [:chart_limit]
            )
            
            # Récupérer TOP 100 pour la table complète
            aggregated_table = (
                filtered_queryset
                .values(field)
                .annotate(count=Count('id'))
                .order_by('-count')
                [:100]
            )
            
            # Calculer le "Others" pour le graphique
            total_in_chart = sum(item['count'] for item in aggregated_chart)
            total_servers = filtered_queryset.count()
            others_count = total_servers - total_in_chart
            
            # Labels et valeurs pour le GRAPHIQUE (avec Others)
            chart_labels = [str(item[field]) if item[field] else 'Unknown' for item in aggregated_chart]
            chart_values = [item['count'] for item in aggregated_chart]
            
            if others_count > 0:
                chart_labels.append('Others')
                chart_values.append(others_count)
            
            # Labels et valeurs pour la TABLE (100 entrées, sans Others)
            table_labels = [str(item[field]) if item[field] else 'Unknown' for item in aggregated_table]
            table_values = [item['count'] for item in aggregated_table]
            
            field_label = settings.CHART_AVAILABLE_FIELDS.get(field, {}).get('label', field)
            
            charts_data.append({
                'field': field_label,
                'type': chart_type,
                'labels': chart_labels,        # Pour le graphique (20 + Others)
                'values': chart_values,        # Pour le graphique
                'table_labels': table_labels,  # Pour la table (100)
                'table_values': table_values,  # Pour la table
                'total': total_servers,
            })
    
    context = {
        'charts_data': json.dumps(charts_data),
        'total_servers': filtered_queryset.count(),
        'filters_applied': request.GET.urlencode(),
    }
    
    return render(request, 'charts.html', context)
