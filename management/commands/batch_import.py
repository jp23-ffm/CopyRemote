# management/commands/batch_import_no_fk.py
import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from django.utils import timezone
from claude.models import Server, ServerStaging, ServerGroupSummary
from collections import defaultdict

class Command(BaseCommand):
    help = 'Batch import with FK constraints disabled'
    
    def handle(self, *args, **options):
        JSON_FILE_PATH = 'c:\\temp\\claude_server.json'
        
        self.stdout.write('Starting FK-disabled batch import...')
        
        try:
            # Step 1: Disable FK constraints globally
            self.disable_foreign_keys()
            
            # Step 2: Load JSON
            data = self.load_json_file(JSON_FILE_PATH)
            
            # Step 3: Import servers to staging
            self.import_to_staging(data)
            
            # Step 4: Promote servers
            self.promote_servers()
            
            # Step 5: Rebuild summaries (simple approach)
            self.rebuild_summaries_simple()
            
            # Step 6: Re-enable FK constraints
            self.enable_foreign_keys()
            
            self.stdout.write(self.style.SUCCESS('Import completed with FK constraints disabled!'))
            
        except Exception as e:
            # Always re-enable FK constraints even if import fails
            try:
                self.enable_foreign_keys()
            except:
                pass
            self.stdout.write(self.style.ERROR(f'Import failed: {e}'))
            raise
    
    def disable_foreign_keys(self):
        """Disable foreign key constraints for the entire import process"""
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA foreign_keys = OFF')
        self.stdout.write('Foreign key constraints DISABLED')
    
    def enable_foreign_keys(self):
        """Re-enable foreign key constraints"""
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA foreign_keys = ON')
        self.stdout.write('Foreign key constraints ENABLED')
    
    def load_json_file(self, json_file):
        """Load JSON file"""
        if not os.path.exists(json_file):
            raise CommandError(f'JSON file not found: {json_file}')
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            if 'servers' in data:
                data = data['servers']
            elif 'data' in data:
                data = data['data']
            else:
                data = [data]
        
        self.stdout.write(f'Loaded {len(data)} records')
        return data
    
    def import_to_staging(self, data):
        """Import to staging"""
        self.stdout.write('Importing to staging...')
        
        # Recreate staging table
        self.recreate_staging_table()
        
        # Import in batches
        servers_to_create = []
        batch_size = 1000
        
        for i, record in enumerate(data):
            try:
                server = self.create_server_from_json(record)
                servers_to_create.append(server)
                
                if len(servers_to_create) >= batch_size:
                    ServerStaging.objects.bulk_create(servers_to_create)
                    servers_to_create = []
                    
            except Exception as e:
                self.stdout.write(f'Skipped record {i}: {e}')
                continue
        
        if servers_to_create:
            ServerStaging.objects.bulk_create(servers_to_create)
        
        staging_count = ServerStaging.objects.count()
        self.stdout.write(f'Staging: {staging_count} records')
    
    def promote_servers(self):
        """Promote servers using table rename"""
        self.stdout.write('Promoting servers...')
        
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS claude_server_backup')
            cursor.execute('ALTER TABLE claude_server RENAME TO claude_server_backup')
            cursor.execute('ALTER TABLE claude_server_staging RENAME TO claude_server')
            
        # Recreate staging for next run
        self.recreate_staging_table()
        self.stdout.write('Server promotion completed')
    
    def rebuild_summaries_simple(self):
        """Rebuild summaries using optimized approach with full field analysis"""
        self.stdout.write('Rebuilding summaries with field analysis...')
        
        # Clear existing summaries
        ServerGroupSummary.objects.all().delete()
        
        # Get ALL servers in one query and group them in Python (much faster)
        self.stdout.write('Loading all servers...')
        all_servers = list(Server.objects.all().order_by('hostname', 'application'))
        
        # Group by hostname in Python (faster than multiple DB queries)
        self.stdout.write('Grouping servers by hostname...')
        #from collections import defaultdict
        hostname_groups = defaultdict(list)
        for server in all_servers:
            hostname_groups[server.hostname].append(server)
        
        # Process groups and create summaries with field analysis
        self.stdout.write(f'Processing {len(hostname_groups)} unique hostnames with field analysis...')
        summaries_to_create = []
        processed = 0
        
        for hostname, server_list in hostname_groups.items():
            field_analysis = self.analyze_server_fields(server_list)
            
            summary = ServerGroupSummary(
                hostname=hostname,
                total_instances=len(server_list),
                constant_fields=field_analysis['constant'],
                variable_fields=field_analysis['variable'],
                primary_server=server_list[0]
            )
            summaries_to_create.append(summary)
            processed += 1
            
            # Progress update every 1000 hostnames
            if processed % 1000 == 0:
                self.stdout.write(f'  Processed {processed}/{len(hostname_groups)} hostnames')
        
        # Single bulk create
        self.stdout.write(f'Creating {len(summaries_to_create)} summaries in bulk...')
        ServerGroupSummary.objects.bulk_create(summaries_to_create, batch_size=1000)
        
        summary_count = ServerGroupSummary.objects.count()
        self.stdout.write(f'Created {summary_count} summaries with full field analysis')
    
    def analyze_server_fields(self, server_list):
        """Analyze fields to determine constant vs variable - optimized version"""
        if len(server_list) == 1:
            # Single server - all fields are constant
            server = server_list[0]
            constant_fields = {}
            for field in server._meta.fields:
                if field.name not in ['id', 'created_at', 'updated_at']:
                    value = getattr(server, field.name)
                    if value is not None:
                        constant_fields[field.name] = str(value)
            return {
                'constant': constant_fields,
                'variable': {}
            }
        
        # Multiple servers - analyze field variations
        field_values = defaultdict(set)
        
        for server in server_list:
            for field in server._meta.fields:
                if field.name not in ['id', 'created_at', 'updated_at']:
                    value = getattr(server, field.name)
                    if value is not None:
                        field_values[field.name].add(str(value))
        
        constant_fields = {}
        variable_fields = {}
        
        for field_name, values in field_values.items():
            if len(values) == 1:
                constant_fields[field_name] = list(values)[0]
            else:
                # Limit preview to avoid overly large JSON
                preview_values = list(values)[:5]  # Max 5 values in preview
                variable_fields[field_name] = {
                    'count': len(values),
                    'preview': f">{len(values)} values" if len(values) > 5 else " | ".join(preview_values)
                }
        
        return {
            'constant': constant_fields,
            'variable': variable_fields
        }
    
    def recreate_staging_table(self):
        """Recreate staging table"""
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS claude_server_staging')
            
            # Copy structure from main table
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='claude_server'")
            result = cursor.fetchone()
            if result:
                create_sql = result[0]
                staging_sql = create_sql.replace('claude_server', 'claude_server_staging')
                cursor.execute(staging_sql)
    
    def create_server_from_json(self, record):
        """Create ServerStaging from JSON"""
        model_fields = {field.name: field for field in ServerStaging._meta.fields if field.name != 'id'}
        server_data = {}
        
        for field_name, field in model_fields.items():
            if field_name in record:
                value = record[field_name]
                
                if value is None:
                    server_data[field_name] = None
                    continue
                
                field_type = field.get_internal_type()
                
                if field_type == 'DateTimeField' and isinstance(value, str):
                    try:
                        if 'T' in value or 'Z' in value or '+' in value:
                            server_data[field_name] = timezone.datetime.fromisoformat(value.replace('Z', '+00:00'))
                        else:
                            naive_dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                            server_data[field_name] = timezone.make_aware(naive_dt)
                    except ValueError:
                        server_data[field_name] = None
                elif field_type == 'DateField' and isinstance(value, str):
                    try:
                        server_data[field_name] = datetime.strptime(value, '%Y-%m-%d').date()
                    except ValueError:
                        server_data[field_name] = None
                elif field_type in ['FloatField', 'DecimalField']:
                    server_data[field_name] = float(value) if value != '' else None
                elif field_type in ['IntegerField', 'BigIntegerField']:
                    server_data[field_name] = int(value) if value != '' else None
                elif field_type == 'BooleanField':
                    if isinstance(value, str):
                        server_data[field_name] = value.lower() in ('true', '1', 'yes', 'on')
                    else:
                        server_data[field_name] = bool(value)
                else:
                    server_data[field_name] = str(value) if value != '' else None
        
        return ServerStaging(**server_data)