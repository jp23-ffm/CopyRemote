# management/commands/debug_fk.py
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from claude.models import Server, ServerGroupSummary

class Command(BaseCommand):
    help = 'Debug foreign key constraint issues'
    
    def handle(self, *args, **options):
        self.stdout.write('=== FK CONSTRAINT DEBUG ===')
        
        # Step 1: Check current state
        self.check_current_state()
        
        # Step 2: Test simple summary creation
        self.test_simple_summary_creation()
        
        # Step 3: Test table operations
        self.test_table_operations()
    
    def check_current_state(self):
        self.stdout.write('\n1. CURRENT STATE:')
        
        server_count = Server.objects.count()
        summary_count = ServerGroupSummary.objects.count()
        
        self.stdout.write(f'   Servers: {server_count}')
        self.stdout.write(f'   Summaries: {summary_count}')
        
        # Check if there are any servers
        if server_count > 0:
            first_server = Server.objects.first()
            self.stdout.write(f'   First server ID: {first_server.id}')
            self.stdout.write(f'   First server hostname: {first_server.hostname}')
        
        # Check existing summaries
        if summary_count > 0:
            first_summary = ServerGroupSummary.objects.first()
            self.stdout.write(f'   First summary hostname: {first_summary.hostname}')
            self.stdout.write(f'   First summary primary_server_id: {first_summary.primary_server_id}')
    
    def test_simple_summary_creation(self):
        self.stdout.write('\n2. TESTING SIMPLE SUMMARY CREATION:')
        
        try:
            # Get a server
            server = Server.objects.first()
            if not server:
                self.stdout.write('   No servers found - cannot test')
                return
            
            self.stdout.write(f'   Using server: {server.hostname} (ID: {server.id})')
            
            # Try to create a summary via ORM
            self.stdout.write('   Creating summary via ORM...')
            
            # Delete existing summary for this hostname to avoid conflicts
            ServerGroupSummary.objects.filter(hostname=server.hostname).delete()
            
            summary = ServerGroupSummary(
                hostname=server.hostname,
                total_instances=1,
                constant_fields={'test': 'value'},
                variable_fields={},
                primary_server=server
            )
            summary.save()
            
            self.stdout.write('   ✓ ORM creation successful')
            
            # Clean up
            summary.delete()
            
        except Exception as e:
            self.stdout.write(f'   ✗ ORM creation failed: {e}')
    
    def test_table_operations(self):
        self.stdout.write('\n3. TESTING TABLE OPERATIONS:')
        
        try:
            # Test staging table creation
            self.stdout.write('   Creating staging table...')
            self.create_simple_staging()
            
            # Test insert to staging
            self.stdout.write('   Testing insert to staging...')
            self.test_staging_insert()
            
            # Test table rename
            self.stdout.write('   Testing table operations...')
            self.test_table_rename()
            
        except Exception as e:
            self.stdout.write(f'   ✗ Table operations failed: {e}')
            import traceback
            self.stdout.write(f'   Full error: {traceback.format_exc()}')
    
    def create_simple_staging(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS debug_staging')
            cursor.execute('''
                CREATE TABLE debug_staging (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname VARCHAR(255) NOT NULL,
                    server_id INTEGER NOT NULL
                )
            ''')
        self.stdout.write('   ✓ Staging table created')
    
    def test_staging_insert(self):
        server = Server.objects.first()
        if not server:
            self.stdout.write('   No servers for testing')
            return
            
        try:
            # Method 1: Raw SQL without parameters (safer for debug)
            with connection.cursor() as cursor:
                hostname_clean = server.hostname.replace("'", "''")  # Escape quotes
                sql = f"INSERT INTO debug_staging (hostname, server_id) VALUES ('{hostname_clean}', {server.id})"
                cursor.execute(sql)
            self.stdout.write('   ✓ Insert to staging successful (method 1)')
            
        except Exception as e1:
            self.stdout.write(f'   Method 1 failed: {e1}')
            
            try:
                # Method 2: Use Django's DB-API 2.0 style
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO debug_staging (hostname, server_id) VALUES (%s, %s)",
                        [server.hostname, server.id]
                    )
                self.stdout.write('   ✓ Insert to staging successful (method 2)')
                
            except Exception as e2:
                self.stdout.write(f'   Method 2 failed: {e2}')
                
                # Method 3: Disable debug during insert
                try:
                    from django.conf import settings
                    old_debug = settings.DEBUG
                    settings.DEBUG = False
                    
                    with connection.cursor() as cursor:
                        cursor.execute(
                            'INSERT INTO debug_staging (hostname, server_id) VALUES (?, ?)',
                            (server.hostname, server.id)
                        )
                    
                    settings.DEBUG = old_debug
                    self.stdout.write('   ✓ Insert to staging successful (method 3 - debug off)')
                    
                except Exception as e3:
                    self.stdout.write(f'   All methods failed. Last error: {e3}')
    
    def test_table_rename(self):
        with connection.cursor() as cursor:
            # Test simple rename
            cursor.execute('ALTER TABLE debug_staging RENAME TO debug_renamed')
            cursor.execute('ALTER TABLE debug_renamed RENAME TO debug_staging')
        
        self.stdout.write('   ✓ Table rename successful')
        
        # Cleanup
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE debug_staging')
        self.stdout.write('   ✓ Cleanup done')
    
    def advanced_debug(self):
        self.stdout.write('\n4. ADVANCED DEBUG:')
        
        # Check table constraints
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                # Check FK constraints status
                cursor.execute('PRAGMA foreign_keys')
                fk_enabled = cursor.fetchone()[0]
                self.stdout.write(f'   Foreign keys enabled: {fk_enabled}')
                
                # Check table schema
                cursor.execute('PRAGMA table_info(claude_servergroupsummary)')
                schema = cursor.fetchall()
                self.stdout.write('   ServerGroupSummary schema:')
                for col in schema:
                    self.stdout.write(f'     {col}')
                
                # Check foreign key list
                cursor.execute('PRAGMA foreign_key_list(claude_servergroupsummary)')
                fks = cursor.fetchall()
                self.stdout.write('   Foreign keys:')
                for fk in fks:
                    self.stdout.write(f'     {fk}')
        
        self.stdout.write('\nDEBUG COMPLETED')