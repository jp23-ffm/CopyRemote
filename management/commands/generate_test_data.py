# management/commands/generate_test_data.py
import random
import string
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from claude.models import Server, ServerGroupSummary
from faker import Faker
from collections import defaultdict
from django.utils import timezone

class Command(BaseCommand):
    help = 'Generates test data for servers with 50 fields'
    
    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=100000, help='Total number of entries to generate')
        parser.add_argument('--unique-servers', type=int, default=20000, help='Number of unique servers')
        parser.add_argument('--clear', action='store_true', help='Clear tables before generating')
        parser.add_argument('--rebuild-summary', action='store_true', help='Rebuild summaries only')
    
    def handle(self, *args, **options):
        fake = Faker(['fr_FR', 'en_US'])
        
        if options['rebuild_summary']:
            self.rebuild_summaries_only()
            return
        
        if options['clear']:
            self.stdout.write('Deleting existing data...')
            ServerGroupSummary.objects.all().delete()
            Server.objects.all().delete()
        
        # Base data configuration (extended for 50 fields)
        data_choices = self.get_extended_data_choices()
        
        # Generate unique hostnames
        unique_hostnames = self.generate_unique_hostnames(options['unique_servers'])
        
        self.stdout.write(f'Generating {options["count"]} entries for {len(unique_hostnames)} unique servers...')
        
        servers_to_create = []
        entries_created = 0
        
        # Distribution: 30% servers with 1 entry, 70% with multiple entries
        single_entry_count = int(len(unique_hostnames) * 0.3)
        multi_entry_hostnames = unique_hostnames[single_entry_count:]
        single_entry_hostnames = unique_hostnames[:single_entry_count]
        
        # Create single entries (30%)
        for hostname in single_entry_hostnames:
            if entries_created >= options['count']:
                break
                
            server = self.create_extended_server_entry(hostname, fake, data_choices)
            servers_to_create.append(server)
            entries_created += 1
        
        # Create multiple entries (70%)
        remaining_entries = options['count'] - entries_created
        entries_per_server = remaining_entries // len(multi_entry_hostnames) if multi_entry_hostnames else 0
        
        for i, hostname in enumerate(multi_entry_hostnames):
            if entries_created >= options['count']:
                break
                
            # Number of entries for this server (between 2 and 12)
            if i < len(multi_entry_hostnames) - 1:
                num_entries = min(
                    random.choices([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 
                                 weights=[25, 20, 15, 12, 10, 8, 5, 3, 1, 0.5, 0.5])[0], 
                    options['count'] - entries_created
                )
            else:
                num_entries = options['count'] - entries_created
            
            # Create base server characteristics
            base_config = self.create_base_server_config(fake, data_choices)
            
            for j in range(num_entries):
                if entries_created >= options['count']:
                    break
                    
                server = self.create_extended_server_with_variations(hostname, fake, data_choices, base_config)
                servers_to_create.append(server)
                entries_created += 1
        
        # Batch insertion
        self.stdout.write(f'Inserting {len(servers_to_create)} entries into database...')
        self.bulk_insert_servers(servers_to_create)
        
        # Statistics
        total_servers = Server.objects.values('hostname').distinct().count()
        total_entries = Server.objects.count()
        self.stdout.write(f'Database: {total_entries} entries for {total_servers} unique servers')
        
        # Build group summaries
        self.stdout.write('Building group summaries...')
        self.build_group_summaries()
        
        self.stdout.write(self.style.SUCCESS('Import completed successfully!'))
    
    def get_extended_data_choices(self):
        """Returns all data choices for the 50 fields"""
        return {
            # System and hardware
            'os': ['Ubuntu 20.04', 'Ubuntu 22.04', 'CentOS 7', 'CentOS 8', 'Windows Server 2019', 'Windows Server 2022', 'RHEL 8', 'RHEL 9', 'Debian 11', 'Debian 12', 'SUSE Linux 15', 'Oracle Linux 8'],
            'ram': ['4GB', '8GB', '16GB', '32GB', '64GB', '128GB', '256GB', '512GB', '1TB'],
            'cpu': ['Intel Xeon E5-2640', 'Intel Xeon Silver 4214', 'Intel Xeon Gold 6248', 'AMD EPYC 7542', 'AMD EPYC 7763', 'Intel Core i7-9700', 'Intel Xeon E3-1270', 'ARM Graviton2', 'Intel Xeon Platinum 8259CL'],
            'storage_type': ['SSD', 'HDD', 'NVMe', 'Hybrid', 'SAN'],
            'storage_size': ['100GB', '250GB', '500GB', '1TB', '2TB', '5TB', '10TB', '20TB'],
            'network_speed': ['1Gbps', '10Gbps', '25Gbps', '40Gbps', '100Gbps'],
            
            # Location and infrastructure
            'datacenter': ['Paris-DC1', 'London-DC2', 'Frankfurt-DC1', 'Amsterdam-DC3', 'Madrid-DC1', 'Milan-DC2', 'Stockholm-DC1', 'Dublin-DC4', 'Warsaw-DC1'],
            'rack': [f'R{i:02d}' for i in range(1, 51)],
            'availability_zone': ['AZ-A', 'AZ-B', 'AZ-C', 'AZ-D'],
            'network_vlan': [f'VLAN-{i}' for i in range(100, 1000, 50)],
            
            # Applications and services
            'applications': ['Apache', 'Nginx', 'Tomcat', 'JBoss', 'WebLogic', 'IIS', 'MySQL', 'PostgreSQL', 'Oracle', 'MongoDB', 'Redis', 'Elasticsearch', 'Jenkins', 'GitLab', 'Nexus', 'SonarQube', 'Prometheus', 'Grafana', 'Docker', 'Kubernetes'],
            'service_level': ['Production', 'Test', 'Development', 'Staging', 'Pre-production', 'Disaster Recovery'],
            'backup_policy': ['Daily', 'Weekly', 'Monthly', 'Real-time', 'None'],
            'monitoring_tool': ['Nagios', 'Zabbix', 'DataDog', 'New Relic', 'Prometheus', 'PRTG', 'SolarWinds'],
            
            # Security and compliance
            'security_zone': ['DMZ', 'Internal', 'Restricted', 'Public', 'Management'],
            'compliance_level': ['SOX', 'PCI-DSS', 'HIPAA', 'GDPR', 'ISO27001', 'SOC2', 'None'],
            'antivirus': ['CrowdStrike', 'Symantec', 'McAfee', 'Trend Micro', 'Windows Defender', 'ESET', 'Sophos'],
            'patch_group': ['Critical', 'Standard', 'Delayed', 'Manual'],
            
            # Management and ownership
            'cost_center': [f'CC-{i:04d}' for i in range(1000, 9999, 100)],
            'business_unit': ['IT', 'Finance', 'HR', 'Sales', 'Marketing', 'Operations', 'R&D', 'Legal'],
            'project_code': [f'PRJ-{random.randint(1000, 9999)}' for _ in range(50)],
            'maintenance_window': ['Sunday 02:00-06:00', 'Saturday 22:00-02:00', 'Daily 01:00-03:00', 'Monthly First Sunday'],
            
            # Performance and metrics
            'cpu_cores': ['2', '4', '8', '16', '32', '64', '128'],
            'virtualization': ['VMware', 'Hyper-V', 'KVM', 'Xen', 'Physical', 'Docker', 'LXC'],
            'os_version': ['7.9', '8.4', '9.1', '20.04.3', '22.04.1', '2019', '2022'],
            
            # Status and states
            'power_state': ['Running', 'Stopped', 'Suspended', 'Maintenance', 'Unknown'],
            'health_status': ['Healthy', 'Warning', 'Critical', 'Unknown', 'Degraded'],
            'deployment_status': ['Active', 'Pending', 'Failed', 'Retired', 'Provisioning'],
        }
    
    def generate_unique_hostnames(self, count):
        """Generates realistic unique hostnames"""
        unique_hostnames = set()
        prefixes = ['web', 'app', 'db', 'cache', 'mail', 'file', 'proxy', 'worker', 'api', 'svc', 'lb', 'fw', 'mon', 'log', 'backup', 'nfs', 'dns', 'dhcp', 'ldap', 'vpn']
        environments = ['prod', 'test', 'dev', 'staging', 'preprod', 'demo', 'sandbox', 'dr']
        datacenters = ['par', 'lon', 'fra', 'ams', 'mad', 'mil', 'sto', 'dub', 'war']
        domains = ['company.com', 'corp.local', 'internal.net', 'cloud.local']
        
        while len(unique_hostnames) < count:
            prefix = random.choice(prefixes)
            env = random.choice(environments)
            num = random.randint(1, 999)
            dc = random.choice(datacenters)
            domain = random.choice(domains)
            
            hostname = f"{prefix}-{env}-{num:03d}.{dc}.{domain}"
            unique_hostnames.add(hostname)
        
        return list(unique_hostnames)
    
    def create_base_server_config(self, fake, data_choices):
        """Creates a base configuration for a server (shared between instances)"""
        return {
            # Fields that generally remain constant
            'os': random.choice(data_choices['os']),
            'ram': random.choice(data_choices['ram']),
            'cpu': random.choice(data_choices['cpu']),
            'datacenter': random.choice(data_choices['datacenter']),
            'owner': fake.company(),
            'business_unit': random.choice(data_choices['business_unit']),
            'cost_center': random.choice(data_choices['cost_center']),
            'support_email': fake.email(),
            'virtualization': random.choice(data_choices['virtualization']),
            'storage_type': random.choice(data_choices['storage_type']),
            'network_speed': random.choice(data_choices['network_speed']),
            'security_zone': random.choice(data_choices['security_zone']),
            'compliance_level': random.choice(data_choices['compliance_level']),
            'rack': random.choice(data_choices['rack']),
            'availability_zone': random.choice(data_choices['availability_zone']),
        }
    
    def create_extended_server_entry(self, hostname, fake, data_choices):
        """Creates a complete server entry with all fields"""
        base_config = self.create_base_server_config(fake, data_choices)
        return self.create_extended_server_with_variations(hostname, fake, data_choices, base_config)
    
    def create_extended_server_with_variations(self, hostname, fake, data_choices, base_config):
        """Creates a server keeping some fields constant and varying others"""
        
        # Generate realistic dates with timezone
        from django.utils import timezone
        
        install_date = fake.date_between(start_date='-3y', end_date='today')
        
        # Generate naive datetime then make it timezone-aware
        naive_last_boot = fake.date_time_between(start_date='-30d', end_date='now')
        last_boot = timezone.make_aware(naive_last_boot) if timezone.is_naive(naive_last_boot) else naive_last_boot
        
        warranty_end = fake.date_between(start_date='today', end_date='+2y')
        
        return Server(
            # Server identity
            hostname=hostname,
            ip_address=fake.ipv4_private(),
            
            # System (often constant)
            os=base_config['os'] if random.random() > 0.1 else random.choice(data_choices['os']),
            os_version=random.choice(data_choices['os_version']),
            ram=base_config['ram'] if random.random() > 0.05 else random.choice(data_choices['ram']),
            cpu=base_config['cpu'] if random.random() > 0.05 else random.choice(data_choices['cpu']),
            cpu_cores=random.choice(data_choices['cpu_cores']),
            
            # Storage
            storage_type=base_config['storage_type'] if random.random() > 0.1 else random.choice(data_choices['storage_type']),
            storage_size=random.choice(data_choices['storage_size']),
            
            # Infrastructure (constant)
            datacenter=base_config['datacenter'],
            rack=base_config['rack'] if random.random() > 0.1 else random.choice(data_choices['rack']),
            availability_zone=base_config['availability_zone'],
            network_vlan=random.choice(data_choices['network_vlan']),
            network_speed=base_config['network_speed'],
            
            # Applications (variable)
            application=random.choice(data_choices['applications']),
            service_level=random.choice(data_choices['service_level']),
            db_instance=f"db_{random.choice(['prod', 'test', 'dev'])}_{random.randint(1, 100)}" if random.random() > 0.4 else None,
            
            # Management (constant)
            owner=base_config['owner'],
            business_unit=base_config['business_unit'],
            cost_center=base_config['cost_center'],
            project_code=random.choice(data_choices['project_code']) if random.random() > 0.3 else None,
            support_email=base_config['support_email'],
            
            # Virtualization
            virtualization=base_config['virtualization'],
            
            # Dates
            install_date=install_date,
            last_boot_time=last_boot,
            warranty_expiry=warranty_end,
            
            # Security
            security_zone=base_config['security_zone'],
            compliance_level=base_config['compliance_level'],
            antivirus=random.choice(data_choices['antivirus']),
            patch_group=random.choice(data_choices['patch_group']),
            
            # Monitoring and maintenance
            monitoring_tool=random.choice(data_choices['monitoring_tool']),
            backup_policy=random.choice(data_choices['backup_policy']),
            maintenance_window=random.choice(data_choices['maintenance_window']),
            
            # Current states (highly variable)
            power_state=random.choice(data_choices['power_state']),
            health_status=random.choice(data_choices['health_status']),
            deployment_status=random.choice(data_choices['deployment_status']),
            
            # Metrics (variable)
            cpu_utilization=round(random.uniform(5.0, 95.0), 1),
            memory_utilization=round(random.uniform(10.0, 90.0), 1),
            disk_utilization=round(random.uniform(20.0, 85.0), 1),
            network_in_mbps=round(random.uniform(0.1, 1000.0), 2),
            network_out_mbps=round(random.uniform(0.1, 1000.0), 2),
            
            # Additional information
            serial_number=fake.uuid4()[:16].upper(),
            asset_tag=f"AST-{random.randint(100000, 999999)}",
            purchase_date=fake.date_between(start_date='-4y', end_date='-1y'),
            
            # Notes and comments (occasional)
            notes=fake.text(max_nb_chars=200) if random.random() > 0.7 else '',
            configuration_notes=fake.sentence() if random.random() > 0.8 else '',
            
            # Additional network information
            dns_primary=fake.ipv4(),
            dns_secondary=fake.ipv4(),
            gateway=fake.ipv4_private(),
            subnet_mask='255.255.255.0',
            
            # Tags and labels (JSON simulated as text)
            tags=f"env:{random.choice(['prod','test','dev'])},team:{random.choice(['backend','frontend','devops','data'])}" if random.random() > 0.5 else '',
        )
    
    def bulk_insert_servers(self, servers_to_create):
        """Optimized batch insertion"""
        batch_size = 2000  # Larger batch for 100k entries
        total = len(servers_to_create)
        
        with transaction.atomic():
            for i in range(0, total, batch_size):
                batch = servers_to_create[i:i + batch_size]
                Server.objects.bulk_create(batch, batch_size=batch_size)
                completed = min(i + batch_size, total)
                self.stdout.write(f'  Inserted {completed:,}/{total:,} entries ({completed/total*100:.1f}%)')
    
    def rebuild_summaries_only(self):
        """Rebuilds summaries only without touching servers"""
        self.stdout.write('Rebuilding group summaries...')
        ServerGroupSummary.objects.all().delete()
        self.build_group_summaries()
        self.stdout.write(self.style.SUCCESS('Summaries rebuilt!'))
    
    def build_group_summaries(self):
        """Builds the ServerGroupSummary table with optimization for 100k entries"""
        self.stdout.write('Retrieving servers for analysis...')
        
        # Process in chunks to avoid overloading memory
        hostnames = list(Server.objects.values_list('hostname', flat=True).distinct())
        self.stdout.write(f'Processing {len(hostnames):,} unique hostnames...')
        
        summaries_to_create = []
        processed = 0
        
        # Process in hostname chunks
        chunk_size = 1000
        for i in range(0, len(hostnames), chunk_size):
            hostname_chunk = hostnames[i:i + chunk_size]
            
            # Retrieve all servers for this chunk
            servers = Server.objects.filter(hostname__in=hostname_chunk).order_by('hostname', 'application')
            
            # Group by hostname
            server_groups = defaultdict(list)
            for server in servers:
                server_groups[server.hostname].append(server)
            
            # Analyze each group
            for hostname, server_list in server_groups.items():
                if not server_list:
                    continue
                
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
            
            # Insert this chunk
            if summaries_to_create:
                ServerGroupSummary.objects.bulk_create(summaries_to_create[-len(server_groups):], batch_size=500)
            
            self.stdout.write(f'  Analyzed {processed:,}/{len(hostnames):,} hostnames ({processed/len(hostnames)*100:.1f}%)')
        
        self.stdout.write(f'Created {len(summaries_to_create):,} group summaries')
    
    def analyze_server_fields(self, server_list):
        """Optimized field analysis for 50 fields"""
        if len(server_list) == 1:
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
        
        # Analysis for multiple servers
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
                    'preview': f">{len(values)}" if len(values) > 5 else " | ".join(preview_values)
                }
        
        return {
            'constant': constant_fields,
            'variable': variable_fields
        }