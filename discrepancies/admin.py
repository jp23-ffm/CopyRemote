from django.contrib import admin
from .models import ServerDiscrepancy, AnalysisSnapshot


@admin.register(ServerDiscrepancy)
class ServerDiscrepancyAdmin(admin.ModelAdmin):
    list_display = ['SERVER_ID', 'analysis_date', 'missing_fields']
    list_filter = ['analysis_date', 'datacenter_ok', 'environment_ok']
    search_fields = ['SERVER_ID']
    date_hierarchy = 'analysis_date'


@admin.register(AnalysisSnapshot)
class AnalysisSnapshotAdmin(admin.ModelAdmin):
    list_display = ['analysis_date', 'total_servers_analyzed', 'servers_with_issues', 'percentage_clean']
    list_filter = ['analysis_date']
    date_hierarchy = 'analysis_date'
    readonly_fields = ['percentage_clean', 'percentage_with_issues']
