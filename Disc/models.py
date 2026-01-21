from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Server(models.Model):
    APP_DESCRIPTION = models.CharField(max_length=100, null=True, blank=True)
    APP_MANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_CRITICALITY = models.CharField(max_length=100, null=True, blank=True)
    APP_ITCLUSTER = models.CharField(max_length=100, null=True, blank=True)
    APP_OWNERBUSINESSLINE = models.CharField(max_length=100, null=True, blank=True)
    APP_PRODUCTIONMANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_PRODUCTIONDOMAINMANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_VITALAPP = models.CharField(max_length=100, null=True, blank=True)
    APP_NAME_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_SECPROFILE = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_MANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_BUSINESSLINEOWNER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_DEVELOPMENTMANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_INFRASTRUCTUREMANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    CAPSULE_PRODUCT = models.CharField(max_length=100, null=True, blank=True)
    ECOSYSTEM = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_OWNER = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_STATE = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_NAME = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_LINKS = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_HOST = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_POWERSTATE = models.CharField(max_length=100, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    ASSETGEN_CABINET = models.CharField(max_length=100, null=True, blank=True)
    CITY = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    DECOMREQ = models.CharField(max_length=100, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    FQDN = models.CharField(max_length=100, null=True, blank=True)
    INFRAVERSION = models.CharField(max_length=100, null=True, blank=True)
    IPADDRESS = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    MANUFACTURER = models.CharField(max_length=100, null=True, blank=True)
    MODEL = models.CharField(max_length=100, null=True, blank=True)
    VLAN = models.CharField(max_length=100, null=True, blank=True)
    NETMASK = models.CharField(max_length=100, null=True, blank=True)
    NETWORKID = models.CharField(max_length=100, null=True, blank=True)
    NETWORKNAME = models.CharField(max_length=100, null=True, blank=True)
    OS = models.CharField(max_length=100, null=True, blank=True)
    OSFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFULLVERSION = models.CharField(max_length=100, null=True, blank=True)
    OSSHORTNAME = models.CharField(max_length=100, null=True, blank=True)
    PAAS_COMMENT = models.CharField(max_length=100, null=True, blank=True)
    PAAS_PHASE = models.CharField(max_length=100, null=True, blank=True)
    PAAS_REQUESTER = models.CharField(max_length=100, null=True, blank=True)
    PERIMETER = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_PRODUCT = models.CharField(max_length=100, null=True, blank=True)
    PROVISIONNINGREQ = models.CharField(max_length=100, null=True, blank=True)
    SERIAL = models.CharField(max_length=100, null=True, blank=True)
    SNOW_STATUS = models.CharField(max_length=100, null=True, blank=True)
    SNOW_SUPPORTGROUP = models.CharField(max_length=100, null=True, blank=True)
    SUBPERIMETER = models.CharField(max_length=100, null=True, blank=True)
    VMTYPE = models.CharField(max_length=100, null=True, blank=True)
    SNOW_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ID = models.CharField(max_length=100, db_index=True)
    SERVER_IP = models.CharField(max_length=100, null=True, blank=True)
    MACHINE_TYPE = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ORPHAN = models.CharField(max_length=100, null=True, blank=True)
    VPIC_CLUSTER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_DATASTORE = models.CharField(max_length=100, null=True, blank=True)
    VPIC_HOST = models.CharField(max_length=100, null=True, blank=True)
    VPIC_OWNER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_POWERSTATE = models.CharField(max_length=100, null=True, blank=True)
    VPIC_RESOURCEPOOL = models.CharField(max_length=100, null=True, blank=True)
    VPIC_VCNAME = models.CharField(max_length=100, null=True, blank=True)
    VPIC_VMGROUPS = models.CharField(max_length=100, null=True, blank=True)
    OBSO_HW_ENDOFEXTENDEDDATE = models.CharField(max_length=100, null=True, blank=True)
    OBSO_HWPURCHASEDATE = models.CharField(max_length=100, null=True, blank=True)
    PARKPLACEENDON = models.CharField(max_length=100, null=True, blank=True)
    PARKPLACESTARTON = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    ASSETGEN_ROOM = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SUBTECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    APP_ITCONTINUITYCRITICALITY = models.CharField(max_length=100, null=True, blank=True)
    SNOW_APPLICATION_VALUE = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_VPIC_CLUSTER = models.CharField(max_length=110, null=True, blank=True)
    AFFINITY = models.CharField(max_length=110, null=True, blank=True)
    SHORT_ENVIRONMENT = models.CharField(max_length=110, null=True, blank=True)
    HYPERVISOR = models.CharField(max_length=110, null=True, blank=True)
    OPENSTACK_INFRA = models.CharField(max_length=110, null=True, blank=True)
    RAM = models.CharField(max_length=100, null=True, blank=True)
    DISK = models.CharField(max_length=100, null=True, blank=True)
    CPU = models.CharField(max_length=100, null=True, blank=True)    
    IDRAC_NAME = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_IP = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_ID = models.CharField(max_length=100, null=True, blank=True)
    DOMAIN = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['OSSHORTNAME']),
            models.Index(fields=['SERIAL']),
            models.Index(fields=['MODEL']),
            models.Index(fields=['PAMELA_PRODUCT']),
            models.Index(fields=['SNOW_DATACENTER']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
            models.Index(fields=['PAMELA_DATACENTER']),
            models.Index(fields=['SNOW_STATUS']),
            models.Index(fields=['SERVER_ID', 'APP_NAME_VALUE']),
        ]

    def __str__(self):
        return self.SERVER_ID


        
class ServerStaging(models.Model):
    APP_DESCRIPTION = models.CharField(max_length=100, null=True, blank=True)
    APP_MANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_CRITICALITY = models.CharField(max_length=100, null=True, blank=True)
    APP_ITCLUSTER = models.CharField(max_length=100, null=True, blank=True)
    APP_OWNERBUSINESSLINE = models.CharField(max_length=100, null=True, blank=True)
    APP_PRODUCTIONMANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_PRODUCTIONDOMAINMANAGER = models.CharField(max_length=100, null=True, blank=True)
    APP_VITALAPP = models.CharField(max_length=100, null=True, blank=True)
    APP_NAME_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_SECPROFILE = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_MANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_BUSINESSLINEOWNER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_DEVELOPMENTMANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_BAMPLUS_INFRASTRUCTUREMANAGER_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    CAPSULE_PRODUCT = models.CharField(max_length=100, null=True, blank=True)
    ECOSYSTEM = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_OWNER = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_STATE = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_EMAIL = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_NAME = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_LINKS = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_HOST = models.CharField(max_length=100, null=True, blank=True)
    OPENSTACK_POWERSTATE = models.CharField(max_length=100, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    ASSETGEN_CABINET = models.CharField(max_length=100, null=True, blank=True)
    CITY = models.CharField(max_length=100, null=True, blank=True)
    COUNTRY = models.CharField(max_length=100, null=True, blank=True)
    DECOMREQ = models.CharField(max_length=100, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    FQDN = models.CharField(max_length=100, null=True, blank=True)
    INFRAVERSION = models.CharField(max_length=100, null=True, blank=True)
    IPADDRESS = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    MANUFACTURER = models.CharField(max_length=100, null=True, blank=True)
    MODEL = models.CharField(max_length=100, null=True, blank=True)
    VLAN = models.CharField(max_length=100, null=True, blank=True)
    NETMASK = models.CharField(max_length=100, null=True, blank=True)
    NETWORKID = models.CharField(max_length=100, null=True, blank=True)
    NETWORKNAME = models.CharField(max_length=100, null=True, blank=True)
    OS = models.CharField(max_length=100, null=True, blank=True)
    OSFAMILY = models.CharField(max_length=100, null=True, blank=True)
    OSFULLVERSION = models.CharField(max_length=100, null=True, blank=True)
    OSSHORTNAME = models.CharField(max_length=100, null=True, blank=True)
    PAAS_COMMENT = models.CharField(max_length=100, null=True, blank=True)
    PAAS_PHASE = models.CharField(max_length=100, null=True, blank=True)
    PAAS_REQUESTER = models.CharField(max_length=100, null=True, blank=True)
    PERIMETER = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_PRODUCT = models.CharField(max_length=100, null=True, blank=True)
    PROVISIONNINGREQ = models.CharField(max_length=100, null=True, blank=True)
    SERIAL = models.CharField(max_length=100, null=True, blank=True)
    SNOW_STATUS = models.CharField(max_length=100, null=True, blank=True)
    SNOW_SUPPORTGROUP = models.CharField(max_length=100, null=True, blank=True)
    SUBPERIMETER = models.CharField(max_length=100, null=True, blank=True)
    VMTYPE = models.CharField(max_length=100, null=True, blank=True)
    SNOW_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ID = models.CharField(max_length=100, db_index=True)
    SERVER_IP = models.CharField(max_length=100, null=True, blank=True)
    MACHINE_TYPE = models.CharField(max_length=100, null=True, blank=True)
    SERVER_ORPHAN = models.CharField(max_length=100, null=True, blank=True)
    VPIC_CLUSTER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_DATASTORE = models.CharField(max_length=100, null=True, blank=True)
    VPIC_HOST = models.CharField(max_length=100, null=True, blank=True)
    VPIC_OWNER = models.CharField(max_length=100, null=True, blank=True)
    VPIC_POWERSTATE = models.CharField(max_length=100, null=True, blank=True)
    VPIC_RESOURCEPOOL = models.CharField(max_length=100, null=True, blank=True)
    VPIC_VCNAME = models.CharField(max_length=100, null=True, blank=True)
    VPIC_VMGROUPS = models.CharField(max_length=100, null=True, blank=True)
    OBSO_HW_ENDOFEXTENDEDDATE = models.CharField(max_length=100, null=True, blank=True)
    OBSO_HWPURCHASEDATE = models.CharField(max_length=100, null=True, blank=True)
    PARKPLACEENDON = models.CharField(max_length=100, null=True, blank=True)
    PARKPLACESTARTON = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    ASSETGEN_ROOM = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SUBTECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    APP_ITCONTINUITYCRITICALITY = models.CharField(max_length=100, null=True, blank=True)
    SNOW_APPLICATION_VALUE = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_VPIC_CLUSTER = models.CharField(max_length=110, null=True, blank=True)
    AFFINITY = models.CharField(max_length=110, null=True, blank=True)
    SHORT_ENVIRONMENT = models.CharField(max_length=110, null=True, blank=True)
    HYPERVISOR = models.CharField(max_length=110, null=True, blank=True)
    OPENSTACK_INFRA = models.CharField(max_length=110, null=True, blank=True)
    RAM = models.CharField(max_length=100, null=True, blank=True)
    DISK = models.CharField(max_length=100, null=True, blank=True)
    CPU = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_NAME = models.CharField(max_length=100, null=True, blank=True)
    IDRAC_IP = models.CharField(max_length=100, null=True, blank=True)
    SUBSCRIPTION_ID = models.CharField(max_length=100, null=True, blank=True)
    DOMAIN = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        managed = False    
    

class ServerGroupSummary(models.Model):

    # Pre-calculated table to optimize grouped display. Recalculated on each data import.

    SERVER_ID = models.CharField(max_length=255, unique=True, db_index=True)
    total_instances = models.PositiveIntegerField()
    constant_fields = models.JSONField(default=dict)  # Constant fields (JSON): {field_name: value}
    variable_fields = models.JSONField(default=dict)  # Variable fields (JSON): {field_name: {"count": 3, "preview": "val1 | val2 | val3"}}
    last_updated = models.DateTimeField(auto_now=True)
    
    @property
    def servers(self):
        return Server.objects.filter(hostname=self.SERVER_ID)  # All servers
        
    class Meta:
        indexes = [
            models.Index(fields=['last_updated']),
            models.Index(fields=['total_instances']),
            models.Index(fields=['SERVER_ID', 'total_instances']),
        ]
        verbose_name = "Server Group Summary"
        verbose_name_plural = "Server Group Summaries"        
    

class ServerGroupSummaryStaging(models.Model):

    # Pre-calculated table to optimize grouped display. Recalculated on each data import.

    SERVER_ID = models.CharField(max_length=255, unique=True, db_index=True)
    total_instances = models.PositiveIntegerField()
    constant_fields = models.JSONField(default=dict)  # Constant fields (JSON): {field_name: value}
    variable_fields = models.JSONField(default=dict)  # Variable fields (JSON): {field_name: {"count": 3, "preview": "val1 | val2 | val3"}}
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        managed = False    
        

class ServerAnnotation(models.Model):
    SERVER_ID = models.CharField(max_length=255, unique=True, db_index=True)
    notes = models.TextField(blank=True, help_text="Current annotation")
    type = models.CharField(max_length=50, null=True, blank=True, help_text="Type of annotation")
    servicenow = models.CharField(max_length=255, blank=True, help_text="ServiceNow RITM number")
    history = models.JSONField(default=list, help_text="Historical entries")
    updated_at = models.DateTimeField(auto_now=True)

    def add_entry(self, text, user, annotation_type, servicenow):
        if not self.history:
            self.history = []

        self.history.append({
            'text': text,
            'user': user.username if user else 'Unknown',
            'date': timezone.now().isoformat(),
            'type': annotation_type,
            'servicenow': servicenow
        })

        self.notes = text
        self.type = annotation_type
        self.servicenow = servicenow
        self.save()

    def get_history_display(self):
        if not self.history:
            return []

        return sorted(self.history, key=lambda x: x['date'], reverse=True)

    def __str__(self):
        return f"{self.SERVER_ID} - {self.notes[:50] if self.notes else 'No annotation'}"

    class Meta:
        ordering = ['SERVER_ID']
        verbose_name = "Server Annotation"
        verbose_name_plural = "Server Annotations"
        
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['updated_at']),
            models.Index(fields=['SERVER_ID', 'type']),
        ]        


class ImportStatus(models.Model):
    date_import = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    nb_entries_created = models.IntegerField(default=0)
    nb_groups_created = models.IntegerField(default=0)
    #source_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


class ServerDiscrepancy(models.Model):
    """
    Stores servers with missing or invalid data in critical fields.
    Populated by analyze_discrepancies command.
    Table is recreated at each analysis via staging table swap.
    """
    SERVER_ID = models.CharField(max_length=100, unique=True, db_index=True)

    # Fields checked for missing data (stores actual values found, NULL if missing)
    APP_NAME_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    OS = models.CharField(max_length=100, null=True, blank=True)
    OSSHORTNAME = models.CharField(max_length=100, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SNOW_SUPPORTGROUP = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_NAME = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    MACHINE_TYPE = models.CharField(max_length=100, null=True, blank=True)
    IPADDRESS = models.CharField(max_length=100, null=True, blank=True)

    # Comma-separated list of missing field names (e.g., "OS,REGION,TECHFAMILY")
    missing_fields = models.TextField(
        blank=True,
        help_text="Comma-separated list of field names that are missing or invalid"
    )
    analysis_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Server Discrepancy"
        verbose_name_plural = "Server Discrepancies"
        ordering = ['SERVER_ID']
        indexes = [
            models.Index(fields=['SERVER_ID']),
            models.Index(fields=['ENVIRONMENT']),
            models.Index(fields=['REGION']),
            models.Index(fields=['analysis_date']),
        ]

    def __str__(self):
        return f"{self.SERVER_ID} - {self.missing_count} missing field(s)"

    @property
    def missing_fields_list(self) -> list:
        """Return missing fields as a list"""
        if not self.missing_fields:
            return []
        return [f.strip() for f in self.missing_fields.split(',') if f.strip()]

    @property
    def missing_count(self) -> int:
        """Return count of missing fields"""
        return len(self.missing_fields_list)


class ServerDiscrepancyStaging(models.Model):
    """
    Staging table for ServerDiscrepancy.
    Created and swapped by analyze_discrepancies command.
    """
    SERVER_ID = models.CharField(max_length=100, unique=True, db_index=True)

    APP_NAME_VALUE = models.CharField(max_length=100, null=True, blank=True)
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_DATACENTER = models.CharField(max_length=100, null=True, blank=True)
    OS = models.CharField(max_length=100, null=True, blank=True)
    OSSHORTNAME = models.CharField(max_length=100, null=True, blank=True)
    ENVIRONMENT = models.CharField(max_length=100, null=True, blank=True)
    REGION = models.CharField(max_length=100, null=True, blank=True)
    TECHFAMILY = models.CharField(max_length=100, null=True, blank=True)
    SNOW_SUPPORTGROUP = models.CharField(max_length=100, null=True, blank=True)
    APP_SUPPORTGROUP_NAME = models.CharField(max_length=100, null=True, blank=True)
    LIVE_STATUS = models.CharField(max_length=100, null=True, blank=True)
    MACHINE_TYPE = models.CharField(max_length=100, null=True, blank=True)
    IPADDRESS = models.CharField(max_length=100, null=True, blank=True)

    missing_fields = models.TextField(blank=True)
    analysis_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
