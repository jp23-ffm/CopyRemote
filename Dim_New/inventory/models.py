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
    SNOW_APPLICATION_AUID = models.CharField(max_length=100, null=True, blank=True)
    SNOW_APPLICATION_NAME = models.CharField(max_length=100, null=True, blank=True)
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
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    DOMAIN = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_ADDM_LASTSEEN = models.CharField(max_length=100, null=True, blank=True)

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
    SNOW_APPLICATION_AUID = models.CharField(max_length=100, null=True, blank=True)
    SNOW_APPLICATION_NAME = models.CharField(max_length=100, null=True, blank=True)
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
    APP_AUID_VALUE = models.CharField(max_length=100, null=True, blank=True)
    DOMAIN = models.CharField(max_length=100, null=True, blank=True)
    PAMELA_ADDM_LASTSEEN = models.CharField(max_length=100, null=True, blank=True)

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
            'servicenow': servicenow,
            'is_active': True,
        })

        self.notes = text
        self.type = annotation_type
        self.servicenow = servicenow
        self.save()

    @property
    def active_annotations(self):
        """History entries not yet resolved (is_active defaults to True for legacy entries)."""
        if not self.history:
            return []
        return [
            {'index': i, **e}
            for i, e in enumerate(self.history)
            if e.get('is_active', True)
        ]

    def resolve_entry(self, entry_index, user):
        """Mark a history entry as resolved and sync current fields."""
        if self.history and 0 <= entry_index < len(self.history):
            self.history[entry_index]['is_active'] = False
            self.history[entry_index]['resolved_at'] = timezone.now().isoformat()
            self.history[entry_index]['resolved_by'] = user.username if user else 'Unknown'
            self._sync_from_active()
            self.save()

    def _sync_from_active(self):
        """Sync notes/type/servicenow from the most recent active entry."""
        active = [e for e in (self.history or []) if e.get('is_active', True)]
        if active:
            latest = max(active, key=lambda x: x.get('date', ''))
            self.notes = latest.get('text', '')
            self.type = latest.get('type', '')
            self.servicenow = latest.get('servicenow', '')
        else:
            self.notes = ''
            self.type = ''
            self.servicenow = ''

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

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


class SnapshotStatus(models.Model):
    """Tracks each run of snapshot_field_counts."""
    date_import      = models.DateTimeField(auto_now_add=True)
    success          = models.BooleanField(default=False)
    message          = models.TextField(blank=True, null=True)
    snapshot_date    = models.DateField(null=True, blank=True)
    nb_rows_inserted = models.IntegerField(default=0)
    nb_fields        = models.IntegerField(default=0)
    nb_errors        = models.IntegerField(default=0)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


class ServerHistoryImportStatus(models.Model):
    """Tracks each run of import_server_history."""
    date_import    = models.DateTimeField(auto_now_add=True)
    success        = models.BooleanField(default=False)
    message        = models.TextField(blank=True, null=True)
    import_date    = models.DateField(null=True, blank=True)   # valid_from used in this run
    dry_run        = models.BooleanField(default=False)
    nb_new         = models.IntegerField(default=0)
    nb_changed     = models.IntegerField(default=0)
    nb_disappeared = models.IntegerField(default=0)
    nb_closed      = models.IntegerField(default=0)
    nb_inserted    = models.IntegerField(default=0)

    def __str__(self):
        return f"{'OK' if self.success else 'KO'} {self.date_import.strftime('%d.%m.%Y %H:%M')}"


class FieldSnapshot(models.Model):
    """Daily breakdown of a tracked field, optionally scoped to a filter value.

    Global rows: filter_field='', filter_value=''.
    Filtered rows: filter_field='REGION', filter_value='EU', etc.
    counts: {field_value: count, ...}
    """
    date = models.DateField(db_index=True)
    field_name = models.CharField(max_length=100)
    filter_field = models.CharField(max_length=100, default='')
    filter_value = models.CharField(max_length=255, default='')
    counts = models.JSONField()

    class Meta:
        unique_together = [('date', 'field_name', 'filter_field', 'filter_value')]
        indexes = [
            models.Index(fields=['field_name', 'filter_field', 'date']),
        ]
        verbose_name = "Field Snapshot"
        verbose_name_plural = "Field Snapshots"


class FieldSnapshotFiltered(models.Model):
    """Daily breakdown of a tracked field with up to two filter dimensions.

    Global: all filter columns = ''.
    Single filter: filter_field/filter_value set, filter_field2=filter_value2=''.
    Double filter: all four columns set (order from filter_combinations config).
    counts: {field_value: count, ...}
    """
    date = models.DateField(db_index=True)
    field_name = models.CharField(max_length=100)
    filter_field = models.CharField(max_length=100, default='')
    filter_value = models.CharField(max_length=255, default='')
    filter_field2 = models.CharField(max_length=100, default='')
    filter_value2 = models.CharField(max_length=255, default='')
    filter_field3 = models.CharField(max_length=100, default='')
    filter_value3 = models.CharField(max_length=255, default='')
    counts = models.JSONField()

    class Meta:
        unique_together = [('date', 'field_name', 'filter_field', 'filter_value', 'filter_field2', 'filter_value2', 'filter_field3', 'filter_value3')]
        indexes = [
            models.Index(fields=['field_name', 'filter_field', 'filter_field2', 'filter_field3', 'date']),
        ]
        verbose_name = "Field Snapshot (Filtered)"
        verbose_name_plural = "Field Snapshots (Filtered)"


class ServerHistory(models.Model):
    """SCD Type 2 history of the server inventory.

    Grain: (SERVER_ID, APP_NAME_VALUE). APP_NAME_VALUE is never NULL; use '' for servers with no app.
    Machine-level attributes (OSSHORTNAME, REGION, …) are duplicated across app-rows for
    the same server+period — this is intentional and enables clean deduplication.
    Compatible with SQLite (dev) and PostgreSQL (prod).
    """
    SERVER_ID       = models.CharField(max_length=255, db_index=True)
    APP_NAME_VALUE  = models.CharField(max_length=255, default='')  # '' = no app assigned

    # Grain: relation (can differ across apps on the same machine)
    APP_CRITICALITY       = models.CharField(max_length=64, null=True, blank=True)
    APP_OWNERBUSINESSLINE = models.CharField(max_length=128, null=True, blank=True)

    # Grain: machine (identical for all app-rows of the same server+period)
    ENVIRONMENT     = models.CharField(max_length=64, null=True, blank=True)
    INFRAVERSION    = models.CharField(max_length=64, null=True, blank=True)
    ECOSYSTEM       = models.CharField(max_length=64, null=True, blank=True)
    PERIMETER       = models.CharField(max_length=64, null=True, blank=True)
    OSSHORTNAME     = models.CharField(max_length=128, null=True, blank=True)
    OSFAMILY        = models.CharField(max_length=64, null=True, blank=True)
    PAMELA_PRODUCT  = models.CharField(max_length=128, null=True, blank=True)
    REGION          = models.CharField(max_length=64, null=True, blank=True)
    SNOW_DATACENTER = models.CharField(max_length=128, null=True, blank=True)
    MACHINE_TYPE    = models.CharField(max_length=64, null=True, blank=True)
    MANUFACTURER    = models.CharField(max_length=128, null=True, blank=True)
    MODEL           = models.CharField(max_length=128, null=True, blank=True)
    SNOW_SUPPORTGROUP = models.CharField(max_length=128, null=True, blank=True)
    SNOW_STATUS     = models.CharField(max_length=32, db_index=True, default='OPERATIONAL')

    # Measures — machine grain, additive (dedup by SERVER_ID before summing
    # when no relation-grain dimension is in the query)
    CPU = models.IntegerField(null=True)
    RAM = models.IntegerField(null=True)

    valid_from = models.DateField(db_index=True)
    valid_to   = models.DateField(null=True, blank=True, db_index=True)  # None = open

    class Meta:
        indexes = [
            models.Index(fields=['valid_from', 'valid_to'], name='inventory_sh_period_idx'),
            models.Index(fields=['APP_NAME_VALUE'],         name='inventory_sh_appname_idx'),
            models.Index(fields=['REGION'],                 name='inventory_sh_region_idx'),
            models.Index(fields=['ENVIRONMENT'],            name='inventory_sh_env_idx'),
            models.Index(fields=['OSSHORTNAME'],            name='inventory_sh_osname_idx'),
            models.Index(fields=['OSFAMILY'],               name='inventory_sh_osfamily_idx'),
            models.Index(fields=['INFRAVERSION'],           name='inventory_sh_infraversion_idx'),
            models.Index(fields=['SNOW_SUPPORTGROUP'],      name='inventory_sh_supportgroup_idx'),
        ]
        verbose_name = 'Server History'
        verbose_name_plural = 'Server History'
