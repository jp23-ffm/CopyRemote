import csv
from django.http import HttpResponse

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