# management/commands/import_json_data.py
import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from django.utils import timezone
from django.core.exceptions import ValidationError
from collections import defaultdict
from claude.models import Server, ServerStaging, ServerGroupSummary

class Command(BaseCommand):
    help = 'Import server data from JSON file with staging support'
    
    def add_arguments(self, parser):
        parser.add_argument('json_file', type=str, help='Path to JSON file containing server data')
        parser.add_argument('--validate-only', action='store_true', help='Only validate JSON without importing')
        parser.add_argument('--use-staging', action='store_true', help='Import to ServerStaging table')
        parser.add_argument('--promote-staging', action='store_true', help='Promote ServerStaging to Server (DANGEROUS)')
        parser.add_argument('--clear-staging', action='store_true', help='Clear staging table before import')
        parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for bulk operations')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without actually doing it')
        parser.add_argument('--rebuild-summary', action='store_true', help='Rebuild summaries after import')
    
    def handle(self, *args, **options):
        # Validate file existence
        json_file = options['json_file']
        if not os.path.exists(json_file):
            raise CommandError(f'JSON file not found: {json_file}')
        
        # Handle different operations
        if options['promote_staging']:
            self.promote_staging_to_production()
            return
        
        # Load and validate JSON
        self.stdout.write('Loading JSON file...')
        data = self.load_json_file(json_file)
        
        if options['validate_only']:
            self.validate_json_data(data)
            return
        
        # Import data
        if options['use_staging']:
            self.import_to_staging(data, options)
        else:
            self.import_to_production(data, options)
    
    def load_json_file(self, json_file):
        """Load and parse JSON file"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Support different JSON structures
            if isinstance(data, dict):
                if 'servers' in data:
                    data = data['servers']  # {servers: [...]}
                elif 'data' in data:
                    data = data['data']     # {data: [...]}
                else:
                    # Single server object
                    data = [data]
            
            self.stdout.write(f'Loaded {len(data)} records from JSON')
            return data
            
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON file: {e}')
        except Exception as e:
            raise CommandError(f'Error reading file: {e}')
    
    def validate_json_data(self, data):
        """Validate JSON data structure and fields"""
        self.stdout.write('Validating JSON data...')
        
        if not isinstance(data, list):
            raise CommandError('JSON data must be a list of server objects')
        
        if len(data) == 0:
            raise CommandError('No server data found in JSON')
        
        # Get expected fields from Server model
        expected_fields = {field.name for field in Server._meta.fields if field.name != 'id'}
        
        errors = []
        warnings = []
        
        for i, record in enumerate(data):
            if not isinstance(record, dict):
                errors.append(f'Record {i}: Must be a dictionary/object')
                continue
            
            # Check required fields
            required_fields = {'hostname'}  # Add other required fields as needed
            missing_required = required_fields - set(record.keys())
            if missing_required:
                errors.append(f'Record {i}: Missing required fields: {missing_required}')
            
            # Check for unknown fields
            unknown_fields = set(record.keys()) - expected_fields
            if unknown_fields:
                warnings.append(f'Record {i}: Unknown fields will be ignored: {unknown_fields}')
            
            # Validate data types for key fields
            if 'hostname' in record and not isinstance(record['hostname'], str):
                errors.append(f'Record {i}: hostname must be a string')
            
            # Validate dates
            date_fields = ['install_date', 'last_boot_time', 'warranty_expiry', 'purchase_date']
            for field in date_fields:
                if field in record and record[field]:
                    try:
                        if isinstance(record[field], str):
                            # Try to parse the date
                            datetime.fromisoformat(record[field].replace('Z', '+00:00'))
                    except ValueError:
                        errors.append(f'Record {i}: {field} has invalid date format: {record[field]}')
        
        # Report results
        if errors:
            for error in errors[:10]:  # Show first 10 errors
                self.stdout.write(self.style.ERROR(f'ERROR: {error}'))
            if len(errors) > 10:
                self.stdout.write(self.style.ERROR(f'... and {len(errors) - 10} more errors'))
            raise CommandError('Validation failed')
        
        if warnings:
            for warning in warnings[:5]:  # Show first 5 warnings
                self.stdout.write(self.style.WARNING(f'WARNING: {warning}'))
            if len(warnings) > 5:
                self.stdout.write(self.style.WARNING(f'... and {len(warnings) - 5} more warnings'))
        
        self.stdout.write(self.style.SUCCESS('JSON validation passed!'))
    
    def import_to_production(self, data, options):
        """Import directly to Server table"""
        self.stdout.write('Importing to production Server table...')
        
        if options['dry_run']:
            self.stdout.write('DRY RUN: Would import the following:')
            self.preview_import(data)
            return
        
        servers_to_create = []
        
        for i, record in enumerate(data):
            try:
                server = self.create_server_from_json(Server, record)
                servers_to_create.append(server)
                
                if len(servers_to_create) >= options['batch_size']:
                    self.bulk_create_servers(Server, servers_to_create, options['batch_size'])
                    servers_to_create = []
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error processing record {i}: {e}'))
                continue
        
        # Import remaining records
        if servers_to_create:
            self.bulk_create_servers(Server, servers_to_create, options['batch_size'])
        
        # Rebuild summaries if requested
        if options['rebuild_summary']:
            self.rebuild_group_summaries()
        
        total_servers = Server.objects.values('hostname').distinct().count()
        total_entries = Server.objects.count()
        self.stdout.write(self.style.SUCCESS(f'Import completed! {total_entries} entries for {total_servers} unique servers'))
    
    def import_to_staging(self, data, options):
        """Import to ServerStaging table"""
        self.stdout.write('Importing to ServerStaging table...')
        
        # Ensure staging table exists
        self.ensure_staging_table_exists()
        
        if options['clear_staging']:
            self.stdout.write('Clearing staging table...')
            ServerStaging.objects.all().delete()
        
        if options['dry_run']:
            self.stdout.write('DRY RUN: Would import the following to staging:')
            self.preview_import(data)
            return
        
        servers_to_create = []
        
        for i, record in enumerate(data):
            try:
                server = self.create_server_from_json(ServerStaging, record)
                servers_to_create.append(server)
                
                if len(servers_to_create) >= options['batch_size']:
                    self.bulk_create_servers(ServerStaging, servers_to_create, options['batch_size'])
                    servers_to_create = []
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error processing record {i}: {e}'))
                continue
        
        # Import remaining records
        if servers_to_create:
            self.bulk_create_servers(ServerStaging, servers_to_create, options['batch_size'])
        
        # Get staging stats
        total_staging = ServerStaging.objects.count()
        unique_staging = ServerStaging.objects.values('hostname').distinct().count()
        
        self.stdout.write(self.style.SUCCESS(f'Staging import completed! {total_staging} entries for {unique_staging} unique servers'))
        self.stdout.write(self.style.WARNING('Use --promote-staging to move data to production'))
    
    def create_server_from_json(self, model_class, record):
        """Create server instance from JSON record"""
        # Get model fields
        model_fields = {field.name: field for field in model_class._meta.fields if field.name != 'id'}
        
        server_data = {}
        
        for field_name, field in model_fields.items():
            if field_name in record:
                value = record[field_name]
                
                # Handle None values
                if value is None:
                    server_data[field_name] = None
                    continue
                
                # Convert data types based on field type
                if hasattr(field, 'get_internal_type'):
                    field_type = field.get_internal_type()
                    
                    if field_type in ['DateTimeField']:
                        if isinstance(value, str):
                            try:
                                # Parse ISO format dates with timezone
                                if 'T' in value or 'Z' in value or '+' in value:
                                    # ISO format with timezone info
                                    server_data[field_name] = timezone.datetime.fromisoformat(
                                        value.replace('Z', '+00:00')
                                    )
                                else:
                                    # Simple datetime string without timezone - make it timezone-aware
                                    naive_dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                                    server_data[field_name] = timezone.make_aware(naive_dt)
                            except ValueError as e:
                                # Try other common formats
                                try:
                                    naive_dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
                                    server_data[field_name] = timezone.make_aware(naive_dt)
                                except ValueError:
                                    self.stdout.write(self.style.ERROR(f'Cannot parse datetime: {value}'))
                                    server_data[field_name] = None
                        else:
                            # If it's already a datetime object, ensure it's timezone-aware
                            if hasattr(value, 'tzinfo') and value.tzinfo is None:
                                server_data[field_name] = timezone.make_aware(value)
                            else:
                                server_data[field_name] = value
                    
                    elif field_type in ['DateField']:
                        if isinstance(value, str):
                            server_data[field_name] = datetime.strptime(value, '%Y-%m-%d').date()
                        else:
                            server_data[field_name] = value
                    
                    elif field_type in ['FloatField', 'DecimalField']:
                        server_data[field_name] = float(value) if value != '' else None
                    
                    elif field_type in ['IntegerField', 'BigIntegerField']:
                        server_data[field_name] = int(value) if value != '' else None
                    
                    elif field_type in ['BooleanField']:
                        if isinstance(value, str):
                            server_data[field_name] = value.lower() in ('true', '1', 'yes', 'on')
                        else:
                            server_data[field_name] = bool(value)
                    
                    else:
                        server_data[field_name] = str(value) if value != '' else None
                else:
                    server_data[field_name] = value
        
        return model_class(**server_data)
    
    def bulk_create_servers(self, model_class, servers, batch_size):
        """Bulk create servers with progress reporting"""
        try:
            with transaction.atomic():
                model_class.objects.bulk_create(servers, batch_size=batch_size)
            self.stdout.write(f'Created {len(servers)} records')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Bulk create failed: {e}'))
            raise
    
    def ensure_staging_table_exists(self):
        """Ensure staging table exists, create it if not"""
        from django.db import connection
        
        try:
            # Try to query the table to see if it exists
            ServerStaging.objects.exists()
            self.stdout.write('Staging table exists')
        except Exception:
            self.stdout.write('Staging table does not exist, creating it...')
            self.create_staging_table()
            self.stdout.write('Staging table created successfully')
    
    def create_staging_table(self):
        """Create staging table with same structure as Server"""
        from django.db import connection
        
        with connection.cursor() as cursor:
            db_vendor = connection.vendor
            
            # Drop existing table if it exists
            if db_vendor == 'postgresql':
                cursor.execute('DROP TABLE IF EXISTS claude_server_staging CASCADE')
            else:  # SQLite
                cursor.execute('DROP TABLE IF EXISTS claude_server_staging')
            
            # Create table by copying structure from Server table
            if db_vendor == 'postgresql':
                cursor.execute('CREATE TABLE claude_server_staging (LIKE claude_server INCLUDING DEFAULTS)')
            else:  # SQLite
                # For SQLite, we need to get the CREATE TABLE statement and modify it
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='claude_server'")
                create_sql = cursor.fetchone()[0]
                staging_sql = create_sql.replace('claude_server', 'claude_server_staging')
                cursor.execute(staging_sql)
    
    def get_database_vendor(self):
        """Get database vendor"""
        return connection.vendor
    
    def promote_staging_to_production(self):
        """Promote staging data to production using fast table rename operations"""
        self.stdout.write(self.style.WARNING('DANGEROUS OPERATION: Promoting staging to production'))
        
        db_vendor = self.get_database_vendor()
        
        # Check staging data
        staging_count = ServerStaging.objects.count()
        production_count = Server.objects.count()
        
        self.stdout.write(f'Staging records: {staging_count}')
        self.stdout.write(f'Production records: {production_count}')
        
        if staging_count == 0:
            raise CommandError('No data in staging table')
        
        try:
            with transaction.atomic():
                backup_table = 'claude_server_backup'
                
                self.stdout.write('Performing fast table swap...')
                
                with connection.cursor() as cursor:
                    # Step 1: Drop old backup table if it exists
                    self.stdout.write('Cleaning up old backup table...')
                    if db_vendor == 'postgresql':
                        cursor.execute(f'DROP TABLE IF EXISTS {backup_table} CASCADE')
                    else:  # SQLite
                        cursor.execute(f'DROP TABLE IF EXISTS {backup_table}')
                    
                    # Step 2: Rename current production table to backup
                    self.stdout.write(f'Backing up current production table to {backup_table}...')
                    if db_vendor == 'postgresql':
                        cursor.execute(f'ALTER TABLE claude_server RENAME TO {backup_table}')
                    else:  # SQLite
                        cursor.execute(f'ALTER TABLE claude_server RENAME TO {backup_table}')
                    
                    # Step 3: Rename staging table to production
                    self.stdout.write('Promoting staging table to production...')
                    if db_vendor == 'postgresql':
                        cursor.execute('ALTER TABLE claude_server_staging RENAME TO claude_server')
                    else:  # SQLite
                        cursor.execute('ALTER TABLE claude_server_staging RENAME TO claude_server')
                    
                    # Step 4: Recreate empty staging table for next use
                    self.stdout.write('Recreating empty staging table...')
                    self.create_staging_table()
                
                self.stdout.write(self.style.SUCCESS('Fast promotion completed successfully!'))
                self.stdout.write(f'Production data backed up as: {backup_table}')
                self.stdout.write('Empty staging table recreated for next import')
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Promotion failed: {e}'))
            self.stdout.write(self.style.ERROR('Attempting to restore from backup...'))
            
            # Try to restore if something went wrong
            try:
                with connection.cursor() as cursor:
                    # If claude_server doesn't exist, restore from backup
                    if db_vendor == 'postgresql':
                        cursor.execute("SELECT to_regclass('claude_server')")
                        if cursor.fetchone()[0] is None:
                            cursor.execute(f'ALTER TABLE {backup_table} RENAME TO claude_server')
                            self.stdout.write('Production table restored from backup')
                    else:  # SQLite
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='claude_server'")
                        if not cursor.fetchone():
                            cursor.execute(f'ALTER TABLE {backup_table} RENAME TO claude_server')
                            self.stdout.write('Production table restored from backup')
            except Exception as restore_error:
                self.stdout.write(self.style.ERROR(f'Restore failed: {restore_error}'))
                self.stdout.write(self.style.ERROR(f'Manual intervention required - backup table: {backup_table}'))
            
            raise
    
    def preview_import(self, data):
        """Preview what would be imported"""
        sample_size = min(3, len(data))
        
        self.stdout.write(f'Would import {len(data)} records. Sample:')
        
        for i in range(sample_size):
            record = data[i]
            hostname = record.get('hostname', 'Unknown')
            os_info = record.get('os', 'Unknown')
            app = record.get('application', 'Unknown')
            
            self.stdout.write(f'  {i+1}. {hostname} - {os_info} - {app}')
        
        if len(data) > sample_size:
            self.stdout.write(f'  ... and {len(data) - sample_size} more records')
    
    def rebuild_group_summaries(self):
        """Rebuild ServerGroupSummary after import"""
        self.stdout.write('Rebuilding group summaries...')
        
        # Clear existing summaries
        ServerGroupSummary.objects.all().delete()
        
        # Get unique hostnames
        hostnames = Server.objects.values_list('hostname', flat=True).distinct()
        
        summaries_to_create = []
        
        for hostname in hostnames:
            servers = list(Server.objects.filter(hostname=hostname).order_by('application'))
            
            if len(servers) == 1:
                # Single server
                constant_fields = {}
                for field in servers[0]._meta.fields:
                    if field.name not in ['id', 'created_at', 'updated_at']:
                        value = getattr(servers[0], field.name)
                        if value is not None:
                            constant_fields[field.name] = str(value)
                
                summary = ServerGroupSummary(
                    hostname=hostname,
                    total_instances=1,
                    constant_fields=constant_fields,
                    variable_fields={},
                    primary_server=servers[0]
                )
            else:
                # Multiple servers - analyze fields
                field_analysis = self.analyze_server_fields(servers)
                summary = ServerGroupSummary(
                    hostname=hostname,
                    total_instances=len(servers),
                    constant_fields=field_analysis['constant'],
                    variable_fields=field_analysis['variable'],
                    primary_server=servers[0]
                )
            
            summaries_to_create.append(summary)
        
        # Bulk create summaries
        ServerGroupSummary.objects.bulk_create(summaries_to_create, batch_size=500)
        self.stdout.write(f'Created {len(summaries_to_create)} group summaries')
    
    def analyze_server_fields(self, server_list):
        """Analyze fields to determine constant vs variable"""
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
                preview_values = list(values)[:5]
                variable_fields[field_name] = {
                    'count': len(values),
                    'preview': f">{len(values)}" if len(values) > 5 else " | ".join(preview_values)
                }
        
        return {
            'constant': constant_fields,
            'variable': variable_fields
        }