Vers la ligne où tu as def server_view(request):, tu charges déjà field_labels.json avec ta fonction get_field_labels().
Dans la partie où tu construis display_servers.append({...}), ajoute juste :


display_servers.append({
    'hostname': SERVER_ID,
    'count': visible_count,
    'total_count': total_count,
    'hidden_count': hidden_count,
    'has_hidden': hidden_count > 0,
    'constant_fields': constant_fields,
    'variable_fields': summary.variable_fields if summary else {},
    'all_instances': server_list,
    'primary_server': primary_server,
    'annotation': annotations_dict.get(SERVER_ID),
    
    # ⭐ AJOUTER CETTE LIGNE :
    'instances_json': json.dumps([{
        'constant_fields': {f.name: str(getattr(s, f.name, '')) for f in constant_fields},
        'variable_fields': {f.name: str(getattr(s, f.name, '')) for f in (summary.variable_fields if summary else [])},
    } for s in server_list], ensure_ascii=False),
})
