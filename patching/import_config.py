"""Configuration of the patching CSV import: column mapping and null handling."""

# CSV column -> PatchingServer field name.
# TODO: adjust the right-hand side once the real model fields are decided.
FIELD_MAP = {
    'servername': 'SERVERNAME',
    'sub_region': 'SUB_REGION',
    'template': 'TEMPLATE',
    'host_comment': 'HOST_COMMENT',
    'slot_id': 'SLOT_ID',
    'schedule_id': 'SCHEDULE_ID',
    'host_default_schedule_comment': 'HOST_DEFAULT_SCHEDULE_COMMENT',
    'server_patching_status': 'SERVER_PATCHING_STATUS',
    'patching_summary': 'PATCHING_SUMMARY',
    'programming_status': 'PROGRAMMING_STATUS',
    'server_campaign_status': 'SERVER_CAMPAIGN_STATUS',
    'next_patch_start_time': 'NEXT_PATCH_START_TIME',
    'last_patch_start_time': 'LAST_PATCH_START_TIME',
    'next_precheck_start_time': 'NEXT_PRECHECK_START_TIME',
    'last_precheck_start_time': 'LAST_PRECHECK_START_TIME',
    'precheck_template': 'PRECHECK_TEMPLATE',
    'precheck_status': 'PRECHECK_STATUS',
    'precheck_summary': 'PRECHECK_SUMMARY',
    'precheck_programming_status': 'PRECHECK_PROGRAMMING_STATUS',
    'movement_blocked': 'MOVEMENT_BLOCKED',
    'latest_patching_tower_job_id': 'LATEST_PATCHING_TOWER_JOB_ID',
    'latest_precheck_tower_job_id': 'LATEST_PRECHECK_TOWER_JOB_ID',
    'next_manual_patch_start_time': 'NEXT_MANUAL_PATCH_START_TIME',
    'last_manual_patch_start_time': 'LAST_MANUAL_PATCH_START_TIME',
    'default_schedule__schedule_start_time': 'DEFAULT_SCHEDULE_START_TIME',
    'default_schedule__schedule_name': 'DEFAULT_SCHEDULE_NAME',
    'default_schedule__schedule_comment': 'DEFAULT_SCHEDULE_COMMENT',
    'default_schedule__paas_bool': 'DEFAULT_SCHEDULE_PAAS_BOOL',
    'default_schedule__wave_name': 'DEFAULT_SCHEDULE_WAVE_NAME',
    'default_schedule__id': 'DEFAULT_SCHEDULE_ID',
    'blacklist__blacklist_name': 'BLACKLIST_NAME',
    'blacklist__blacklist_comment': 'BLACKLIST_COMMENT',
    'blacklist__is_permanent': 'BLACKLIST_IS_PERMANENT',
    'blacklist__start_time': 'BLACKLIST_START_TIME',
    'blacklist__end_time': 'BLACKLIST_END_TIME',
    'blacklist__requester': 'BLACKLIST_REQUESTER',
    'blacklist__risk_card': 'BLACKLIST_RISK_CARD',
    'blacklist__servername': 'BLACKLIST_SERVERNAME',
    'blacklist__campaign_name': 'BLACKLIST_CAMPAIGN_NAME',
    'blacklist__id': 'BLACKLIST_ID',
}

# Unique key of a row in the CSV (must be mapped to a unique model field).
KEY_COLUMN = 'servername'

# Raw values treated as "no value" (compared lowercase, after strip).
NULL_VALUES = {'', 'null'}

# For these CSV columns, a null value is stored as EMPTY_VALUE instead of NULL.
# Rule of thumb: fields used to filter / group in the UI (statuses, names,
# flags), so that "no value" shows up as a selectable value.
# Dates, ids, comments and summaries stay NULL.
EMPTY_VALUE = 'EMPTY'
EMPTY_FIELDS = {
    'sub_region',
    'template',
    'server_patching_status',
    'programming_status',
    'server_campaign_status',
    'precheck_template',
    'precheck_status',
    'precheck_programming_status',
    'movement_blocked',
    'default_schedule__schedule_name',
    'default_schedule__paas_bool',
    'default_schedule__wave_name',
    'blacklist__blacklist_name',
    'blacklist__is_permanent',
    'blacklist__campaign_name',
}
