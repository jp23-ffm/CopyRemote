# views.py
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
    datacenter_filter = request.GET.get('datacenter', '').strip()  # Changed from location to datacenter
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
    
    # Processing according to display mode
    display_servers = []
    
    if flat_view:
        print(f"[TIMING] Flat mode selected")
        processing_start = time.time()
        
        # EARLY PAGINATION - Paginate the QuerySet directly
        pagination_start = time.time()
        
        # Use smaller pages for 300k entries
        paginator = Paginator(filtered_servers, 50)  # Reduced from 50 to 25
        page_obj_raw = paginator.get_page(request.GET.get('page'))
        
        print(f"[TIMING] QuerySet pagination created: {time.time() - pagination_start:.3f}s")
        
        # Now convert only the current page to list (50 elements max)
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
        
        # Create a pagination object with transformed data
        class MockPageObj:
            def __init__(self, object_list, page_info):
                self.object_list = object_list
                self.number = page_info.number
                self.paginator = page_info.paginator
                
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
        
        page_obj = MockPageObj(display_servers, page_obj_raw)
        
        print(f"[TIMING] Flat mode processed: {time.time() - processing_start:.3f}s")
        
        # Statistics for flat mode - use count() which is optimized
        stats_start = time.time()
        total_servers_stat = paginator.count  # Faster than recalculating
        total_instances_stat = total_servers_stat
        print(f"[TIMING] Flat mode statistics: {time.time() - stats_start:.3f}s")
        
    else:
        # GROUPED MODE - Different optimization
        print(f"[TIMING] Grouped mode selected")
        processing_start = time.time()
        
        # In grouped mode, we need to group BEFORE pagination
        # Strategy: paginate hostnames directly if no filters
        
        grouping_start = time.time()
        
        # If no filters, we can paginate hostnames directly
        has_filters = any([hostname_filter, os_filter, datacenter_filter, owner_filter, application_filter])
        
        if not has_filters:
            # Without filters, paginate hostnames directly to avoid loading everything
            print("[OPTIMIZATION] No filters - hostname pagination")
            
            page_number = int(request.GET.get('page', 1))
            hostnames_per_page = 50  # 25 hostnames per page
            start_hostname = (page_number - 1) * hostnames_per_page
            end_hostname = start_hostname + hostnames_per_page
            
            # Get only the hostnames for current page
            unique_hostnames = list(
                Server.objects.values_list('hostname', flat=True)
                .distinct()
                .order_by('hostname')[start_hostname:end_hostname]
            )
            
            print(f"[OPTIMIZATION] Page {page_number}: hostnames {start_hostname} to {end_hostname-1} ({len(unique_hostnames)} hostnames)")
            
            # Filter to keep only these hostnames
            filtered_servers = filtered_servers.filter(hostname__in=unique_hostnames)
            
            # For final pagination, we'll need the total hostname count
            total_hostnames_count = Server.objects.values('hostname').distinct().count()
            print(f"[OPTIMIZATION] Total unique hostnames in DB: {total_hostnames_count}")
        
        # Now convert to list (reduced dataset)
        filtered_servers_list = list(filtered_servers)
        print(f"[TIMING] List conversion for grouping ({len(filtered_servers_list)} entries): {time.time() - grouping_start:.3f}s")
        
        # Group filtered servers by hostname
        grouping_step_start = time.time()
        filtered_server_groups = defaultdict(list)
        for server in filtered_servers_list:
            filtered_server_groups[server.hostname].append(server)
        
        print(f"[TIMING] Grouping by hostname ({len(filtered_server_groups)} groups): {time.time() - grouping_step_start:.3f}s")
        
        # Get concerned hostnames
        hostnames_list = list(filtered_server_groups.keys())
        
        # Get pre-calculated summaries
        summaries_start = time.time()
        if hostnames_list:
            summaries_queryset = ServerGroupSummary.objects.filter(hostname__in=hostnames_list)
            summaries_dict = {summary.hostname: summary for summary in summaries_queryset}
            print(f"[TIMING] Summaries retrieved ({len(summaries_dict)} summaries): {time.time() - summaries_start:.3f}s")
        else:
            summaries_dict = {}
            print(f"[TIMING] No summaries to retrieve: {time.time() - summaries_start:.3f}s")
        
        # Create display objects for grouping
        analysis_start = time.time()
        fallback_count = 0
        grouped_servers = []
        
        for hostname, server_list in filtered_server_groups.items():
            if not server_list:
                continue
            
            # Get pre-calculated summary
            summary = summaries_dict.get(hostname)
            
            if summary:
                # Use pre-calculated data
                visible_count = len(server_list)
                total_count = summary.total_instances
                hidden_count = max(0, total_count - visible_count)
                
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
            else:
                # Fallback: recalculate on the fly if no summary
                fallback_count += 1
                field_analysis = analyze_server_fields(server_list)
                
                grouped_servers.append({
                    'hostname': hostname,
                    'count': len(server_list),
                    'total_count': len(server_list),
                    'hidden_count': 0,
                    'has_hidden': False,
                    'constant_fields': field_analysis['constant'],
                    'variable_fields': field_analysis['variable'],
                    'all_instances': server_list,
                    'primary_server': server_list[0],
                    'is_flat_mode': False,
                })
        
        print(f"[TIMING] Group analysis (fallback: {fallback_count}): {time.time() - analysis_start:.3f}s")
        
        # PAGINATION of groups
        pagination_start = time.time()
        
        if not has_filters:
            # Special pagination for no-filter mode
            # We've already paginated hostnames, so no need to repaginate
            
            # Create a mock paginator object with the correct total count
            hostnames_per_page = 50
            total_pages = (total_hostnames_count + hostnames_per_page - 1) // hostnames_per_page
            current_page = int(request.GET.get('page', 1))
            
            class CustomPaginator:
                def __init__(self, count, per_page):
                    self.count = count
                    self.per_page = per_page
                    self.num_pages = (count + per_page - 1) // per_page
            
            class CustomPageObj:
                def __init__(self, object_list, page_number, paginator_obj):
                    self.object_list = object_list
                    self.number = page_number
                    self.paginator = paginator_obj
                    
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
            
            custom_paginator = CustomPaginator(total_hostnames_count, hostnames_per_page)
            page_obj_raw = CustomPageObj(grouped_servers, current_page, custom_paginator)
            
            print(f"[TIMING] Custom pagination: page {current_page}/{custom_paginator.num_pages}")
            
        else:
            # Normal pagination for filter mode
            paginator = Paginator(grouped_servers, 50)
            page_obj_raw = paginator.get_page(request.GET.get('page'))
            print(f"[TIMING] Normal pagination: {len(grouped_servers)} groups")
        
        
        # Get annotations only for groups in current page
        annotations_start = time.time()
        hostnames_in_page = [group['hostname'] for group in page_obj_raw]
        annotations_dict = {}
        if hostnames_in_page:
            annotations = ServerAnnotation.objects.filter(hostname__in=hostnames_in_page)
            annotations_dict = {ann.hostname: ann for ann in annotations}
        print(f"[TIMING] Annotations for current page ({len(annotations_dict)} annotations): {time.time() - annotations_start:.3f}s")
        
        # Add annotations to page groups
        for group in page_obj_raw:
            group['annotation'] = annotations_dict.get(group['hostname'])
            display_servers.append(group)
        
        page_obj = page_obj_raw
        
        print(f"[TIMING] Pagination and annotations for grouped mode: {time.time() - pagination_start:.3f}s")
        print(f"[TIMING] Total grouped mode: {time.time() - processing_start:.3f}s")
        
        # Statistics for grouped mode
        if not has_filters:
            # Without filters: get true global statistics
            total_servers_stat = Server.objects.values('hostname').distinct().count()
            total_instances_stat = Server.objects.count()
        else:
            # With filters: use current filtered results
            total_servers_stat = len(grouped_servers)
            total_instances_stat = sum(group['count'] for group in grouped_servers)
    
    # Statistics for filters (distinct values for selects)
    stats_start = time.time()
    filter_stats = {
        'os_choices': Server.objects.values_list('os', flat=True).distinct().exclude(os__isnull=True).exclude(os='').order_by('os'),
        'datacenter_choices': Server.objects.values_list('datacenter', flat=True).distinct().exclude(datacenter__isnull=True).exclude(datacenter='').order_by('datacenter'),
        'owner_choices': Server.objects.values_list('owner', flat=True).distinct().exclude(owner__isnull=True).exclude(owner='').order_by('owner'),
    }
    print(f"[TIMING] Filter statistics: {time.time() - stats_start:.3f}s")
    
    context_start = time.time()
    
    # Check if we have active filters
    has_filters = any([hostname_filter, os_filter, datacenter_filter, owner_filter, application_filter])
    
    # Context with current filters
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


def analyze_server_fields(server_list):
    """
    Analyze fields of a server group to identify
    those that are constant vs those that vary
    """
    if len(server_list) == 1:
        # Single server, all fields are "constant"
        server = server_list[0]
        constant_fields = {}
        for field in server._meta.fields:
            if field.name not in ['id', 'created_at', 'updated_at']:
                value = getattr(server, field.name)
                if value:  # Ignore null/empty values
                    constant_fields[field.name] = str(value)
        return {
            'constant': constant_fields,
            'variable': {}
        }
    
    # Multiple servers, analyze differences
    field_values = defaultdict(set)
    
    # Collect all values for each field
    for server in server_list:
        for field in server._meta.fields:
            if field.name not in ['id', 'created_at', 'updated_at']:
                value = getattr(server, field.name)
                if value:  # Ignore null/empty values
                    field_values[field.name].add(str(value))
    
    # Separate constant fields from variable ones
    constant_fields = {}
    variable_fields = {}
    
    for field_name, values in field_values.items():
        if len(values) == 1:
            # Constant field
            constant_fields[field_name] = list(values)[0]
        else:
            # Variable field
            variable_fields[field_name] = {
                'count': len(values),
                'preview': f">{len(values)}" if len(values) > 3 else " | ".join(list(values)[:3])
            }
    
    return {
        'constant': constant_fields,
        'variable': variable_fields
    }