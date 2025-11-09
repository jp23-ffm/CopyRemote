"""

if summary:
    # Use pre-calculated data
    visible_count = len(server_list)
    total_count = summary.total_instances
    hidden_count = max(0, total_count - visible_count)
    
    grouped_servers.append({
        'hostname': hostname,
        'count': visible_count,
        'constant_fields': summary.constant_fields,  # ← Champs globaux
        'variable_fields': summary.variable_fields,  # ← Orange avec pipes
        # ...
    })



if summary:
    visible_count = len(server_list)
    total_count = summary.total_instances
    hidden_count = max(0, total_count - visible_count)
    
    # Si une seule occurrence visible, afficher ses valeurs réelles
    if visible_count == 1:
        single_server = server_list[0]
        constant_fields = {}
        for field in single_server._meta.fields:
            if field.name not in ['id', 'created_at', 'updated_at']:
                value = getattr(single_server, field.name)
                if value:
                    constant_fields[field.name] = str(value)
        
        grouped_servers.append({
            'hostname': hostname,
            'count': visible_count,
            'total_count': total_count,
            'hidden_count': hidden_count,
            'has_hidden': hidden_count > 0,
            'constant_fields': constant_fields,  # ← Valeurs réelles
            'variable_fields': {},  # ← Pas de variables
            'all_instances': server_list,
            'primary_server': server_list[0],
            'is_flat_mode': False,
        })
    else:
        # Logique normale pour plusieurs occurrences
        grouped_servers.append({
            'hostname': hostname,
            'count': visible_count,
            'total_count': total_count,
            'hidden_count': hidden_count,
            'has_hidden': hidden_count > 0,
            'constant_fields': summary.constant_fields,
            'variable_fields': summary.variable_fields,
            'all_instances': server_list,
            'primary_server': server_list[0],
            'is_flat_mode': False,
        })

"""        
    
"""
{% with field_value=server_group.primary_server|lookup:field.name %}

{% with field_value=server_group.all_instances.0|lookup:field.name %}

"""


# views.py - Refactored with separated processing functions
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from collections import defaultdict
from .models import Server, ServerGroupSummary, ServerAnnotation
import time
import json
import csv

def server_list(request):
    start_time = time.time()
    print(f"[TIMING] View start: {time.time():.3f}")
    
    # Get filter parameters
    hostname_filter = request.GET.get('hostname', '').strip()
    os_filter = request.GET.get('os', '').strip()
    datacenter_filter = request.GET.get('datacenter', '').strip()
    owner_filter = request.GET.get('owner', '').strip()
    application_filter = request.GET.get('application', '').strip()
    
    # Display mode parameters
    flat_view = request.GET.get('view', '') == 'flat'
    edit_mode = request.GET.get('edit', '') == 'true'
    
    print(f"[TIMING] Parameters retrieved: {time.time() - start_time:.3f}s")
    filter_start = time.time()
    
    # Get filtered servers (QuerySet, not yet evaluated)
    filtered_servers = Server.objects.all()
    
    # Apply filters
    if hostname_filter:
        filtered_servers = filtered_servers.filter(hostname__icontains=hostname_filter)
    if os_filter:
        filtered_servers = filtered_servers.filter(os__icontains=os_filter)
    if datacenter_filter:
        filtered_servers = filtered_servers.filter(datacenter__icontains=datacenter_filter)
    if owner_filter:
        filtered_servers = filtered_servers.filter(owner__icontains=owner_filter)
    if application_filter:
        filtered_servers = filtered_servers.filter(application__icontains=application_filter)
    
    # Order filtered results
    filtered_servers = filtered_servers.order_by('hostname', 'application')
    
    print(f"[TIMING] Filters applied: {time.time() - filter_start:.3f}s")
    
    # Get model fields (exclude technical fields)
    fields_start = time.time()
    model_fields = get_model_fields()
    print(f"[TIMING] Model fields: {time.time() - fields_start:.3f}s")
    
    # Check if we have active filters
    has_filters = any([hostname_filter, os_filter, datacenter_filter, owner_filter, application_filter])
    
    # Process according to display mode
    if flat_view:
        result = process_flat_view(filtered_servers, request)
    else:
        result = process_grouped_view(filtered_servers, request, has_filters)
    
    # Common filter statistics (for dropdowns)
    filter_stats_start = time.time()
    filter_stats = get_filter_stats()
    print(f"[TIMING] Filter statistics: {time.time() - filter_stats_start:.3f}s")
    
    # Build context
    context_start = time.time()
    context = {
        'page_obj': result['page_obj'],
        'model_fields': model_fields,
        'total_servers': result['total_servers_stat'],
        'total_instances': result['total_instances_stat'],
        'has_filters': has_filters,
        'flat_view': flat_view,
        'edit_mode': edit_mode,
        'filter_stats': filter_stats,
        'current_filters': {
            'hostname': hostname_filter,
            'os': os_filter,
            'datacenter': datacenter_filter,
            'owner': owner_filter,
            'application': application_filter,
        }
    }
    
    print(f"[TIMING] Context prepared: {time.time() - context_start:.3f}s")
    print(f"[TIMING] TOTAL VIEW: {time.time() - start_time:.3f}s")
    
    return render(request, 'inventory/server_list.html', context)


def process_flat_view(filtered_servers, request):
    """Process flat view mode - direct server pagination"""
    print(f"[TIMING] Flat mode selected")
    processing_start = time.time()
    
    # Direct server pagination
    pagination_start = time.time()
    paginator = Paginator(filtered_servers, 50)
    page_obj_raw = paginator.get_page(request.GET.get('page'))
    print(f"[TIMING] Server pagination created: {time.time() - pagination_start:.3f}s")
    
    # Convert only current page to list
    conversion_start = time.time()
    current_page_servers = list(page_obj_raw)
    print(f"[TIMING] Current page conversion ({len(current_page_servers)} elements): {time.time() - conversion_start:.3f}s")
    
    # Get annotations only for current page
    annotations_start = time.time()
    annotations_dict = get_annotations_for_page([s.hostname for s in current_page_servers])
    print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")
    
    # Transform servers to display format
    transform_start = time.time()
    display_servers = []
    for server in current_page_servers:
        display_servers.append({
            'hostname': server.hostname,
            'count': 1,
            'total_count': 1,
            'hidden_count': 0,
            'has_hidden': False,
            'constant_fields': {},
            'variable_fields': {},
            'all_instances': [server],
            'primary_server': server,
            'is_flat_mode': True,
            'annotation': annotations_dict.get(server.hostname)
        })
    print(f"[TIMING] Data transformation for flat mode: {time.time() - transform_start:.3f}s")
    
    page_obj = create_page_wrapper(display_servers, page_obj_raw)
    
    print(f"[TIMING] Flat mode processed: {time.time() - processing_start:.3f}s")
    
    return {
        'page_obj': page_obj,
        'total_servers_stat': paginator.count,
        'total_instances_stat': paginator.count
    }


def process_grouped_view(filtered_servers, request, has_filters):
    """Process grouped view mode - hostname pagination with summaries"""
    print(f"[TIMING] Grouped mode selected")
    processing_start = time.time()
    
    # Step 1: Get filtered hostnames
    hostnames_start = time.time()
    filtered_hostnames_qs = (filtered_servers
        .values('hostname')
        .distinct()
        .order_by('hostname')
    )
    print(f"[TIMING] Filtered hostnames query prepared: {time.time() - hostnames_start:.3f}s")
    
    # Step 2: Paginate hostnames
    pagination_start = time.time()
    hostnames_paginator = Paginator(filtered_hostnames_qs, 50)
    hostnames_page = hostnames_paginator.get_page(request.GET.get('page'))
    print(f"[TIMING] Hostnames pagination: {time.time() - pagination_start:.3f}s")
    
    # Step 3: Get servers for hostnames in current page
    servers_start = time.time()
    hostnames_in_page = [item['hostname'] for item in hostnames_page]
    servers_for_page = filtered_servers.filter(hostname__in=hostnames_in_page)
    servers_list = list(servers_for_page)
    print(f"[TIMING] Servers for page conversion ({len(servers_list)} servers for {len(hostnames_in_page)} hostnames): {time.time() - servers_start:.3f}s")
    
    # Step 4: Group servers by hostname
    grouping_start = time.time()
    server_groups = defaultdict(list)
    for server in servers_list:
        server_groups[server.hostname].append(server)
    print(f"[TIMING] Grouping by hostname ({len(server_groups)} groups): {time.time() - grouping_start:.3f}s")
    
    # Step 5: Get pre-calculated summaries
    summaries_start = time.time()
    summaries_dict = {}
    missing_summaries = 0
    if hostnames_in_page:
        summaries_queryset = ServerGroupSummary.objects.filter(hostname__in=hostnames_in_page)
        summaries_dict = {summary.hostname: summary for summary in summaries_queryset}
        missing_summaries = len(hostnames_in_page) - len(summaries_dict)
    print(f"[TIMING] Summaries retrieved ({len(summaries_dict)} summaries, {missing_summaries} missing): {time.time() - summaries_start:.3f}s")
    
    # Step 6: Create display objects
    analysis_start = time.time()
    display_servers = []
    
    for hostname in hostnames_in_page:  # Maintain page order
        server_list = server_groups.get(hostname, [])
        if not server_list:
            continue
            
        summary = summaries_dict.get(hostname)
        
        if summary:
            # Use pre-calculated data
            visible_count = len(server_list)
            total_count = summary.total_instances
            hidden_count = max(0, total_count - visible_count)
            
            # CRITICAL FIX: If only one visible occurrence, show its real values
            if visible_count == 1:
                single_server = server_list[0]
                constant_fields = {}
                for field in single_server._meta.fields:
                    if field.name not in ['id', 'created_at', 'updated_at']:
                        value = getattr(single_server, field.name)
                        if value:
                            constant_fields[field.name] = str(value)
                
                display_servers.append({
                    'hostname': hostname,
                    'count': visible_count,
                    'total_count': total_count,
                    'hidden_count': hidden_count,
                    'has_hidden': hidden_count > 0,
                    'constant_fields': constant_fields,  # Real values from the single server
                    'variable_fields': {},  # No variable fields for single occurrence
                    'all_instances': server_list,
                    'primary_server': server_list[0],
                    'is_flat_mode': False,
                })
            else:
                # Multiple visible occurrences: use summary data
                display_servers.append({
                    'hostname': hostname,
                    'count': visible_count,
                    'total_count': total_count,
                    'hidden_count': hidden_count,
                    'has_hidden': hidden_count > 0,
                    'constant_fields': summary.constant_fields,
                    'variable_fields': summary.variable_fields,
                    'all_instances': server_list,
                    'primary_server': server_list[0],
                    'is_flat_mode': False,
                })
        else:
            # Missing summary - show basic info only
            display_servers.append({
                'hostname': hostname,
                'count': len(server_list),
                'total_count': len(server_list),
                'hidden_count': 0,
                'has_hidden': False,
                'constant_fields': {},  # Empty - will show "-" in template
                'variable_fields': {},
                'all_instances': server_list,
                'primary_server': server_list[0],
                'is_flat_mode': False,
            })
    
    print(f"[TIMING] Group analysis (missing summaries: {missing_summaries}): {time.time() - analysis_start:.3f}s")
    
    # Step 7: Get annotations for current page
    annotations_start = time.time()
    annotations_dict = get_annotations_for_page(hostnames_in_page)
    
    # Add annotations to display servers
    for server_group in display_servers:
        server_group['annotation'] = annotations_dict.get(server_group['hostname'])
    
    print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")
    
    # Step 8: Create page object
    page_obj = create_page_wrapper(display_servers, hostnames_page)
    
    print(f"[TIMING] Total grouped mode: {time.time() - processing_start:.3f}s")
    
    # Calculate statistics
    stats_start = time.time()
    if has_filters:
        total_servers_stat = hostnames_paginator.count
        total_instances_stat = filtered_servers.count()
    else:
        total_servers_stat = Server.objects.values('hostname').distinct().count()
        total_instances_stat = Server.objects.count()
    print(f"[TIMING] Statistics calculation: {time.time() - stats_start:.3f}s")
    
    return {
        'page_obj': page_obj,
        'total_servers_stat': total_servers_stat,
        'total_instances_stat': total_instances_stat
    }


def get_model_fields():
    """Get model fields for display"""
    model_fields = []
    excluded_fields = ['id', 'created_at', 'updated_at', 'dns_primary', 'dns_secondary', 'gateway', 'subnet_mask']
    
    for field in Server._meta.fields:
        if field.name not in excluded_fields:
            model_fields.append({
                'name': field.name,
                'verbose_name': field.verbose_name or field.name.replace('_', ' ').title(),
                'is_hostname': field.name == 'hostname'
            })
    
    # Always add annotations column
    model_fields.append({
        'name': 'annotations',
        'verbose_name': 'Annotations',
        'is_hostname': False
    })
    
    return model_fields


def get_annotations_for_page(hostnames_list):
    """Get annotations for given hostnames"""
    annotations_dict = {}
    if hostnames_list:
        annotations = ServerAnnotation.objects.filter(hostname__in=hostnames_list)
        annotations_dict = {ann.hostname: ann for ann in annotations}
    return annotations_dict


def get_filter_stats():
    """Get filter statistics for dropdowns"""
    return {
        'os_choices': Server.objects.values_list('os', flat=True).distinct().exclude(os__isnull=True).exclude(os='').order_by('os'),
        'datacenter_choices': Server.objects.values_list('datacenter', flat=True).distinct().exclude(datacenter__isnull=True).exclude(datacenter='').order_by('datacenter'),
        'owner_choices': Server.objects.values_list('owner', flat=True).distinct().exclude(owner__isnull=True).exclude(owner='').order_by('owner'),
    }


def create_page_wrapper(object_list, source_page):
    """Create a unified page object wrapper for both modes"""
    class UnifiedPageObj:
        def __init__(self, objects, source):
            self.object_list = objects
            self.number = source.number
            self.paginator = source.paginator
            
        def __iter__(self):
            return iter(self.object_list)
            
        def has_previous(self):
            return self.number > 1
            
        def has_next(self):
            return self.number < self.paginator.num_pages
            
        def previous_page_number(self):
            return self.number - 1 if self.has_previous() else None
            
        def next_page_number(self):
            return self.number + 1 if self.has_next() else None
            
        def has_other_pages(self):
            return self.paginator.num_pages > 1
    
    return UnifiedPageObj(object_list, source_page)


@login_required
@require_http_methods(["GET", "POST"])
def edit_annotation(request, hostname):
    """View to edit server annotations"""
    
    if request.method == 'GET':
        annotation = ServerAnnotation.objects.filter(hostname=hostname).first()
        
        data = {
            'hostname': hostname,
            'status': annotation.status if annotation else 'production',
            'custom_status': annotation.custom_status if annotation else '',
            'notes': annotation.notes if annotation else '',
            'priority': annotation.priority if annotation else 'normal',
        }
        
        return JsonResponse(data)
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            annotation, created = ServerAnnotation.objects.get_or_create(
                hostname=hostname,
                defaults={
                    'created_by': request.user,
                    'updated_by': request.user,
                }
            )
            
            annotation.status = data.get('status', 'production')
            annotation.custom_status = data.get('custom_status', '')
            annotation.notes = data.get('notes', '')
            annotation.priority = data.get('priority', 'normal')
            annotation.updated_by = request.user
            annotation.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Annotation saved successfully',
                'annotation': {
                    'status': annotation.get_display_status(),
                    'priority': annotation.priority,
                    'notes': annotation.notes,
                    'updated_by': annotation.updated_by.username,
                    'updated_at': annotation.updated_at.strftime('%d/%m/%Y %H:%M')
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error saving: {str(e)}'
            }, status=400)
            
            
def export_grouped_csv(request):
    """Export grouped view as CSV (one row per hostname, collapsed mode)"""
    
    # Get filter parameters (same as server_list view)
    hostname_filter = request.GET.get('hostname', '').strip()
    os_filter = request.GET.get('os', '').strip()
    datacenter_filter = request.GET.get('datacenter', '').strip()
    owner_filter = request.GET.get('owner', '').strip()
    application_filter = request.GET.get('application', '').strip()
    
    # Apply filters
    filtered_servers = Server.objects.all()
    
    if hostname_filter:
        filtered_servers = filtered_servers.filter(hostname__icontains=hostname_filter)
    if os_filter:
        filtered_servers = filtered_servers.filter(os__icontains=os_filter)
    if datacenter_filter:
        filtered_servers = filtered_servers.filter(datacenter__icontains=datacenter_filter)
    if owner_filter:
        filtered_servers = filtered_servers.filter(owner__icontains=owner_filter)
    if application_filter:
        filtered_servers = filtered_servers.filter(application__icontains=application_filter)
    
    # Get unique hostnames
    hostnames = (filtered_servers
                 .values('hostname')
                 .distinct()
                 .order_by('hostname'))
    
    # Group servers by hostname
    from collections import defaultdict
    server_groups = defaultdict(list)
    for server in filtered_servers.order_by('hostname', 'application'):
        server_groups[server.hostname].append(server)
    
    # Get summaries
    hostname_list = [item['hostname'] for item in hostnames]
    summaries_dict = {}
    if hostname_list:
        summaries = ServerGroupSummary.objects.filter(hostname__in=hostname_list)
        summaries_dict = {s.hostname: s for s in summaries}
    
    # Get annotations
    annotations_dict = {}
    if hostname_list:
        annotations = ServerAnnotation.objects.filter(hostname__in=hostname_list)
        annotations_dict = {ann.hostname: ann for ann in annotations}
    
    # Create HTTP response with CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="servers_grouped_export.csv"'
    
    # Use semicolon as delimiter
    writer = csv.writer(response, delimiter=';')
    
    # Get field list (exclude technical fields)
    excluded_fields = ['id', 'created_at', 'updated_at', 'dns_primary', 'dns_secondary', 'gateway', 'subnet_mask']
    field_names = []
    field_verbose_names = []
    
    for field in Server._meta.fields:
        if field.name not in excluded_fields:
            field_names.append(field.name)
            field_verbose_names.append(field.verbose_name or field.name.replace('_', ' ').title())
    
    # Add custom columns
    header = ['Instance Count', 'Total Instances', 'Hidden Count'] + field_verbose_names + ['Annotation Status', 'Annotation Priority', 'Annotation Notes']
    writer.writerow(header)
    
    # Helper function to clean field values
    def clean_value(value):
        """Remove line breaks and return clean string"""
        if value is None:
            return ''
        text = str(value)
        # Replace \r\n, \n, \r with space
        text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
        # Remove multiple consecutive spaces
        text = ' '.join(text.split())
        return text
    
    # Write data rows
    for hostname_item in hostnames:
        hostname = hostname_item['hostname']
        server_list = server_groups.get(hostname, [])
        
        if not server_list:
            continue
        
        summary = summaries_dict.get(hostname)
        annotation = annotations_dict.get(hostname)
        
        visible_count = len(server_list)
        total_count = summary.total_instances if summary else visible_count
        hidden_count = max(0, total_count - visible_count)
        
        # Start row with counts
        row = [visible_count, total_count, hidden_count]
        
        # If only one visible instance, show its real values
        if visible_count == 1:
            single_server = server_list[0]
            for field_name in field_names:
                value = getattr(single_server, field_name, '')
                row.append(clean_value(value))
        else:
            # Multiple instances: use summary data
            if summary:
                for field_name in field_names:
                    # Check if constant field
                    if field_name in summary.constant_fields:
                        row.append(clean_value(summary.constant_fields[field_name]))
                    # Check if variable field
                    elif field_name in summary.variable_fields:
                        # Show preview of variable values
                        preview = summary.variable_fields[field_name].get('preview', '')
                        row.append(clean_value(preview))
                    else:
                        row.append('')
            else:
                # No summary available
                row.extend([''] * len(field_names))
        
        # Add annotation data
        if annotation:
            row.append(clean_value(annotation.get_display_status()))
            row.append(clean_value(annotation.priority))
            row.append(clean_value(annotation.notes or ''))
        else:
            row.extend(['', '', ''])
        
        writer.writerow(row)
    
    return response
    
 
@login_required
@require_http_methods(["GET"])
def get_annotation(request, hostname):
    """
    Récupère les données d'une annotation
    """
    try:
        annotation = ServerAnnotation.objects.get(hostname=hostname)
        
        return JsonResponse({
            'success': True,
            'status': annotation.status,
            'custom_status': annotation.custom_status,
            'notes': annotation.notes,
            'priority': annotation.priority,
        })
        
    except ServerAnnotation.DoesNotExist:
        # Retourner les valeurs par défaut si l'annotation n'existe pas
        return JsonResponse({
            'success': True,
            'status': 'production',
            'custom_status': '',
            'notes': '',
            'priority': 'normal',
        })


@login_required
@require_http_methods(["POST"])
def save_annotation(request, hostname):
    """
    Sauvegarde ou met à jour une annotation
    L'historique est automatiquement ajouté par la méthode save() du modèle
    """
    try:
        data = json.loads(request.body)
        
        # Récupérer ou créer l'annotation
        annotation, created = ServerAnnotation.objects.get_or_create(
            hostname=hostname,
            defaults={
                'created_by': request.user,
                'updated_by': request.user
            }
        )
        
        # Si ce n'est pas une création, on met à jour l'utilisateur
        if not created:
            annotation.updated_by = request.user
        
        # Mettre à jour les champs
        annotation.status = data.get('status', 'production')
        annotation.custom_status = data.get('custom_status', '')
        annotation.notes = data.get('notes', '')
        annotation.priority = data.get('priority', 'normal')
        
        # Sauvegarder (l'historique sera ajouté automatiquement)
        annotation.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Annotation sauvegardée avec succès',
            'annotation': {
                'hostname': annotation.hostname,
                'status': annotation.status,
                'display_status': annotation.get_display_status(),
                'priority': annotation.priority,
                'notes': annotation.notes,
                'history_count': annotation.get_history_count()
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erreur lors de la sauvegarde: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def annotation_history(request, hostname):
    """
    Retourne l'historique JSON de l'annotation
    """
    try:
        annotation = ServerAnnotation.objects.get(hostname=hostname)
        
        # L'historique est déjà en JSON dans annotation.history
        history_data = []
        
        # S'assurer que history est une liste
        if not isinstance(annotation.history, list):
            annotation.history = []
        
        for entry in annotation.history:
            # Enrichir les données pour l'affichage
            status = entry.get('status', 'production')
            custom_status = entry.get('custom_status', '')
            
            # Déterminer le display_status
            if status == 'custom' and custom_status:
                display_status = custom_status
            else:
                display_status = dict(ServerAnnotation.STATUS_CHOICES).get(status, status)
            
            history_data.append({
                'timestamp': entry.get('timestamp'),
                'changed_at': entry.get('timestamp'),  # Alias pour compatibilité
                'change_type': entry.get('change_type', 'update'),
                'changed_by': entry.get('changed_by', 'Unknown'),
                'status': status,
                'custom_status': custom_status,
                'priority': entry.get('priority', 'normal'),
                'notes': entry.get('notes', ''),
                # Labels pour l'affichage
                'display_status': display_status,
                'priority_display': dict(ServerAnnotation.PRIORITY_CHOICES).get(
                    entry.get('priority', 'normal'), 'Normal'
                ),
            })
        
        return JsonResponse({
            'success': True,
            'hostname': hostname,
            'history': history_data,
            'count': len(history_data)
        })
        
    except ServerAnnotation.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Annotation non trouvée',
            'history': []
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'history': []
        }, status=500)