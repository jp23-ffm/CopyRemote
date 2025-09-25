# views.py - Optimized version with unified pagination
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from collections import defaultdict
from .models import Server, ServerGroupSummary, ServerAnnotation
import time
import json

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
    
    fields_start = time.time()
    
    # Get model fields (exclude technical fields)
    model_fields = []
    excluded_fields = ['id', 'created_at', 'updated_at', 'dns_primary', 'dns_secondary', 'gateway', 'subnet_mask' ]
    
    for field in Server._meta.fields:
        if field.name not in excluded_fields:
            model_fields.append({
                'name': field.name,
                'verbose_name': field.verbose_name or field.name.replace('_', ' ').title(),
                'is_hostname': field.name == 'hostname'
            })
    
    # Always add the annotations column
    model_fields.append({
        'name': 'annotations',
        'verbose_name': 'Annotations',
        'is_hostname': False
    })
    
    print(f"[TIMING] Model fields: {time.time() - fields_start:.3f}s")
    
    # Check if we have active filters
    has_filters = any([hostname_filter, os_filter, datacenter_filter, owner_filter, application_filter])
    
    # Processing according to display mode
    display_servers = []
    
    if flat_view:
        print(f"[TIMING] Flat mode selected")
        processing_start = time.time()
        
        # FLAT MODE - Direct server pagination
        pagination_start = time.time()
        
        paginator = Paginator(filtered_servers, 50)
        page_obj_raw = paginator.get_page(request.GET.get('page'))
        
        print(f"[TIMING] Server pagination created: {time.time() - pagination_start:.3f}s")
        
        # Convert only the current page to list
        conversion_start = time.time()
        current_page_servers = list(page_obj_raw)
        print(f"[TIMING] Current page conversion ({len(current_page_servers)} elements): {time.time() - conversion_start:.3f}s")
        
        # Get annotations only for current page
        annotations_start = time.time()
        annotations_dict = {}
        hostnames_in_page = [server.hostname for server in current_page_servers]
        if hostnames_in_page:
            annotations = ServerAnnotation.objects.filter(hostname__in=hostnames_in_page)
            annotations_dict = {ann.hostname: ann for ann in annotations}
        print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")
        
        # Process servers from current page
        transform_start = time.time()
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
        
        # Statistics for flat mode
        total_servers_stat = paginator.count
        total_instances_stat = total_servers_stat
        
    else:
        # GROUPED MODE - Unified hostname pagination approach
        print(f"[TIMING] Grouped mode selected")
        processing_start = time.time()
        
        # Step 1: Get filtered hostnames (applying all filters)
        hostnames_start = time.time()
        filtered_hostnames_qs = (filtered_servers
            .values('hostname')
            .distinct()
            .order_by('hostname')
        )
        print(f"[TIMING] Filtered hostnames query prepared: {time.time() - hostnames_start:.3f}s")
        
        # Step 2: Paginate hostnames
        pagination_start = time.time()
        hostnames_paginator = Paginator(filtered_hostnames_qs, 50)  # 50 hostnames per page
        hostnames_page = hostnames_paginator.get_page(request.GET.get('page'))
        print(f"[TIMING] Hostnames pagination: {time.time() - pagination_start:.3f}s")
        
        # Step 3: Get servers only for hostnames in current page
        servers_start = time.time()
        hostnames_in_page = [item['hostname'] for item in hostnames_page]
        servers_for_page = filtered_servers.filter(hostname__in=hostnames_in_page)
        
        # Now convert to list (much smaller dataset)
        servers_list = list(servers_for_page)
        print(f"[TIMING] Servers for page conversion ({len(servers_list)} servers for {len(hostnames_in_page)} hostnames): {time.time() - servers_start:.3f}s")
        
        # Step 4: Group servers by hostname
        grouping_start = time.time()
        server_groups = defaultdict(list)
        for server in servers_list:
            server_groups[server.hostname].append(server)
        print(f"[TIMING] Grouping by hostname ({len(server_groups)} groups): {time.time() - grouping_start:.3f}s")
        
        # Step 5: Get pre-calculated summaries for hostnames in page
        summaries_start = time.time()
        if hostnames_in_page:
            summaries_queryset = ServerGroupSummary.objects.filter(hostname__in=hostnames_in_page)
            summaries_dict = {summary.hostname: summary for summary in summaries_queryset}
            print(f"[TIMING] Summaries retrieved ({len(summaries_dict)} summaries): {time.time() - summaries_start:.3f}s")
        else:
            summaries_dict = {}
        
        # Step 6: Create display objects
        analysis_start = time.time()
        fallback_count = 0
        
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
                # Missing summary
                fallback_count += 1
                field_analysis = analyze_server_fields(server_list)
                
                display_servers.append({
                    'hostname': hostname,
                    'count': len(server_list),
                    'total_count': len(server_list),
                    'hidden_count': 0,
                    'has_hidden': False,
                    'constant_fields': {'status': 'Summary missing - please rebuild'},
                    'variable_fields': {},
                    'all_instances': server_list,
                    'primary_server': server_list[0],
                    'is_flat_mode': False,
                })
        
        print(f"[TIMING] Group analysis (fallback: {fallback_count}): {time.time() - analysis_start:.3f}s")
        
        # Step 7: Get annotations for current page
        annotations_start = time.time()
        annotations_dict = {}
        if hostnames_in_page:
            annotations = ServerAnnotation.objects.filter(hostname__in=hostnames_in_page)
            annotations_dict = {ann.hostname: ann for ann in annotations}
        
        # Add annotations to display servers
        for server_group in display_servers:
            server_group['annotation'] = annotations_dict.get(server_group['hostname'])
        
        print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")
        
        # Step 8: Create page object with correct pagination info
        page_obj = create_page_wrapper(display_servers, hostnames_page)
        
        print(f"[TIMING] Total grouped mode: {time.time() - processing_start:.3f}s")
        
        # Statistics for grouped mode
        stats_start = time.time()
        if has_filters:
            # With filters: calculate from filtered data
            total_servers_stat = hostnames_paginator.count
            total_instances_stat = filtered_servers.count()
        else:
            # Without filters: get global stats
            total_servers_stat = Server.objects.values('hostname').distinct().count()
            total_instances_stat = Server.objects.count()
        print(f"[TIMING] Statistics calculation: {time.time() - stats_start:.3f}s")
    
    # Filter statistics (for dropdowns)
    filter_stats_start = time.time()
    filter_stats = {
        'os_choices': Server.objects.values_list('os', flat=True).distinct().exclude(os__isnull=True).exclude(os='').order_by('os'),
        'datacenter_choices': Server.objects.values_list('datacenter', flat=True).distinct().exclude(datacenter__isnull=True).exclude(datacenter='').order_by('datacenter'),
        'owner_choices': Server.objects.values_list('owner', flat=True).distinct().exclude(owner__isnull=True).exclude(owner='').order_by('owner'),
    }
    print(f"[TIMING] Filter statistics: {time.time() - filter_stats_start:.3f}s")
    
    # Context preparation
    context_start = time.time()
    context = {
        'page_obj': page_obj,
        'model_fields': model_fields,
        'total_servers': total_servers_stat,
        'total_instances': total_instances_stat,
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
    
    return render(request, 'claude/server_list.html', context)


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
        # Get existing annotation or create a new one
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
        # Save annotation
        try:
            data = json.loads(request.body)
            
            annotation, created = ServerAnnotation.objects.get_or_create(
                hostname=hostname,
                defaults={
                    'created_by': request.user,
                    'updated_by': request.user,
                }
            )
            
            # Update fields
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


