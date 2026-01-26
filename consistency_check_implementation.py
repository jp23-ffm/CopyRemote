"""
=================================================================================
CODE SNIPPETS FOR ADDING LIVE/SNOW CONSISTENCY CHECK
=================================================================================

This file contains all the code modifications needed to add a consistency check
between LIVE_STATUS and SNOW_STATUS fields.

Instructions:
1. Add the new field to models.py
2. Update the analyze_servers() function
3. Update bulk_insert_discrepancies() if needed
4. Add counter to AnalysisSnapshot model
5. Update create_analysis_snapshot() function
6. Add widget to JSON config
7. Run migrations

=================================================================================
"""

# =================================================================================
# 1. ADD TO models.py - ServerDiscrepancy model
# =================================================================================

"""
Add this field to your ServerDiscrepancy model:
"""

class ServerDiscrepancy(models.Model):
    # ... your existing fields ...
    
    # === NEW FIELD ===
    live_snow_consistency_ok = models.BooleanField(default=False, db_index=True)
    # === END NEW FIELD ===


# =================================================================================
# 2. ADD TO models.py - AnalysisSnapshot model
# =================================================================================

"""
Add this field to your AnalysisSnapshot model:
"""

class AnalysisSnapshot(models.Model):
    # ... your existing fields ...
    
    # === NEW FIELD ===
    missing_live_snow_inconsistent_count = models.IntegerField(default=0)
    # === END NEW FIELD ===


# =================================================================================
# 3. UPDATE analyze_servers() function
# =================================================================================

"""
In your analyze_servers() function, add this logic inside the main server loop:
"""

def analyze_servers():
    # ... your existing code ...
    
    for server in queryset.iterator(chunk_size=50000):
        server_id = server.SERVER_ID
        data = server_data[server_id]
        
        # === EXISTING CODE: Check each field ===
        for field in FIELDS_TO_CHECK:
            value = getattr(server, field, None)
            
            if field not in data['field_values'] or is_value_missing(data['field_values'][field]):
                data['field_values'][field] = value
            
            if is_value_missing(value):
                data['missing_fields'].add(field)
        
        # === NEW CODE: Check LIVE/SNOW consistency ===
        live_status = getattr(server, 'LIVE_STATUS', None)
        snow_status = getattr(server, 'SNOW_STATUS', None)
        
        # Check if there's an inconsistency
        is_consistent = True
        if live_status and live_status.upper() == 'ALIVE':
            if snow_status and snow_status.upper() in ['RETIRED', 'NOT_OPERATIONAL', 'NOT OPERATIONAL']:
                is_consistent = False
                data['missing_fields'].add('LIVE_SNOW_INCONSISTENT')
        
        # Store the consistency status
        data['field_values']['live_snow_consistency_ok'] = is_consistent
        # === END NEW CODE ===
    
    # ... rest of your code ...


# =================================================================================
# 4. UPDATE bulk_insert_discrepancies() function
# =================================================================================

"""
In your bulk_insert_discrepancies() function, add to field_to_ok_column mapping:
"""

def bulk_insert_discrepancies(records):
    if not records:
        return
    
    # Mapping of the fields to their ok columns
    field_to_ok_column = {
        'LIVE_STATUS': 'live_status_ok',
        'OSSHORTNAME': 'osshortname_ok',
        'OSFAMILY': 'osfamily_ok',
        'MACHINE_TYPE': 'machine_type_ok',
        'MANUFACTURER': 'manufacturer_ok',
        'COUNTRY': 'country_ok',
        'APP_AUID_VALUE': 'app_auid_value_ok',
        'APP_NAME_VALUE': 'app_name_value_ok',
        'REGION': 'region_ok',
        'CITY': 'city_ok',
        'INFRAVERSION': 'infraversion_ok',
        'IPADDRESS': 'ipaddress_ok',
        # === NEW MAPPING ===
        'LIVE_SNOW_CONSISTENCY': 'live_snow_consistency_ok',
        # === END NEW MAPPING ===
    }
    
    # ... rest of your existing code ...


# =================================================================================
# 5. UPDATE create_analysis_snapshot() function
# =================================================================================

"""
In your create_analysis_snapshot() function, add to field_mapping:
"""

def create_analysis_snapshot(stats, analysis_date, duration):
    """Create a snapshot of the analysis results"""
    from discrepancies.models import AnalysisSnapshot
    
    # Mapping des champs vers les attributs du snapshot
    field_mapping = {
        'LIVE_STATUS': 'missing_live_status_count',
        'OSSHORTNAME': 'missing_osshortname_count',
        'OSFAMILY': 'missing_osfamily_count',
        'MACHINE_TYPE': 'missing_machine_type_count',
        'MANUFACTURER': 'missing_manufacturer_count',
        'COUNTRY': 'missing_country_count',
        'APP_AUID_VALUE': 'missing_app_auid_value_count',
        'APP_NAME_VALUE': 'missing_app_name_value_count',
        'REGION': 'missing_region_count',
        'CITY': 'missing_city_count',
        'INFRAVERSION': 'missing_infraversion_count',
        'IPADDRESS': 'missing_ipaddress_count',
        # === NEW MAPPING ===
        'LIVE_SNOW_INCONSISTENT': 'missing_live_snow_inconsistent_count',
        # === END NEW MAPPING ===
    }
    
    snapshot = AnalysisSnapshot(
        analysis_date=analysis_date,
        total_servers_analyzed=stats['total_entries'],
        servers_with_issues=stats['servers_with_discrepancies'],
        servers_clean=stats['total_entries'] - stats['servers_with_discrepancies'],
        duration_seconds=duration,
    )
    
    # Fill the counters per field
    for field, count_attr in field_mapping.items():
        count = stats.get('discrepancies_by_field', {}).get(field, 0)
        setattr(snapshot, count_attr, count)
    
    snapshot.save()
    write_log(f"Created analysis snapshot: {snapshot.id}")
    
    return snapshot


# =================================================================================
# 6. ADD TO config/discrepancies_dashboard.json
# =================================================================================

"""
Add this widget to your JSON configuration file under "widgets" array:
"""

# Add this object to the "widgets" array in your JSON:
{
  "id": "live_snow_inconsistency",
  "type": "gauge",
  "size": "small",
  "title": "Live/Snow Issues",
  "icon": "⚠️",
  "metric": "missing_live_snow_inconsistent_count",
  "link": "/servers/?live_snow_consistency_ok=False"
}

# Also add to the "historic_section" > "metrics" array:
{
  "id": "live_snow_inconsistent",
  "label": "Live/Snow Inconsistency",
  "metric": "missing_live_snow_inconsistent_count",
  "color": "#e83e8c"
}


# =================================================================================
# 7. MIGRATION COMMANDS
# =================================================================================

"""
After making all changes above, run these commands:

1. Create migrations:
   python manage.py makemigrations discrepancies

2. Apply migrations:
   python manage.py migrate

3. Run analysis:
   python manage.py analyze_discrepancies

4. Check dashboard:
   Visit: http://localhost:8000/discrepancies/dashboard/
"""


# =================================================================================
# 8. OPTIONAL: VIEW FILTERING
# =================================================================================

"""
If you want to add filtering in your servers table view, add this:
"""

def servers_table_view(request):
    # ... your existing code ...
    
    servers = ServerDiscrepancy.objects.all()
    
    # === NEW CODE: Filter by consistency ===
    if request.GET.get('live_snow_consistency_ok') == 'False':
        servers = servers.filter(live_snow_consistency_ok=False)
    # === END NEW CODE ===
    
    # ... rest of your view code ...


# =================================================================================
# COMPLETE JSON CONFIG EXAMPLE
# =================================================================================

"""
Here's a complete example of what your config/discrepancies_dashboard.json
should look like with the new widget:
"""

COMPLETE_JSON_EXAMPLE = '''
{
  "dashboard": {
    "title": "Server Data Quality Dashboard",
    "widgets": [
      {
        "id": "overall_quality",
        "type": "gauge",
        "size": "large",
        "title": "Overall Data Quality",
        "metric": "percentage_clean",
        "thresholds": {
          "critical": 80,
          "warning": 95,
          "good": 100
        },
        "colors": {
          "critical": "#dc3545",
          "warning": "#ffc107",
          "good": "#28a744"
        }
      },
      {
        "id": "live_status_quality",
        "type": "gauge",
        "size": "small",
        "title": "Live Status",
        "icon": "⚡",
        "metric": "missing_live_status_count",
        "link": "/servers/?live_status_ok=False"
      },
      {
        "id": "live_snow_inconsistency",
        "type": "gauge",
        "size": "small",
        "title": "Live/Snow Issues",
        "icon": "⚠️",
        "metric": "missing_live_snow_inconsistent_count",
        "link": "/servers/?live_snow_consistency_ok=False"
      }
    ],
    "historic_section": {
      "enabled": true,
      "title": "Quality Trend",
      "default_metric": "servers_with_issues",
      "days": 30,
      "metrics": [
        {
          "id": "all_issues",
          "label": "All Issues",
          "metric": "servers_with_issues",
          "color": "#dc3545"
        },
        {
          "id": "live_status",
          "label": "Missing Live Status",
          "metric": "missing_live_status_count",
          "color": "#28a744"
        },
        {
          "id": "live_snow_inconsistent",
          "label": "Live/Snow Inconsistency",
          "metric": "missing_live_snow_inconsistent_count",
          "color": "#e83e8c"
        }
      ]
    }
  }
}
'''


# =================================================================================
# TESTING
# =================================================================================

"""
To test your implementation:

1. Create some test data with ALIVE + RETIRED status
2. Run the analysis command
3. Check the dashboard - you should see the new gauge
4. Click on the gauge - it should filter to show only inconsistent servers
5. Check the trend chart - select "Live/Snow Inconsistency" from dropdown
"""


# =================================================================================
# NOTES
# =================================================================================

"""
IMPORTANT NOTES:

1. The field name 'LIVE_SNOW_INCONSISTENT' is used in the analysis to track
   which servers have this specific issue in their missing_fields text.

2. The boolean field 'live_snow_consistency_ok' is used for fast filtering
   in the database.

3. Make sure your SNOW_STATUS values match exactly. Common variations:
   - 'RETIRED' vs 'Retired' vs 'retired'
   - 'NOT_OPERATIONAL' vs 'NOT OPERATIONAL' vs 'not operational'
   
   Adjust the check in analyze_servers() to match your actual data.

4. You can add more consistency checks following the same pattern:
   - Add a new _ok field to ServerDiscrepancy
   - Add logic in analyze_servers()
   - Add counter to AnalysisSnapshot
   - Add widget to JSON config
"""
