from rest_framework import serializers
from businesscontinuity.models import Server as BCServer, ServerUnique
from inventory.models import Server as InventoryServer


class GenericQuerySerializer(serializers.Serializer):
    index = serializers.ChoiceField(choices=["reportapp", "businesscontinuity"])
    filters = serializers.DictField(required=False)
    fields = serializers.ListField(child=serializers.CharField(), required=False)
    excludefields = serializers.ListField(child=serializers.CharField(), required=False)


class EnrichSerializer(serializers.Serializer):
    index = serializers.ChoiceField(choices=["businesscontinuity", "inventory"])
    fields = serializers.ListField(child=serializers.CharField(), required=True)


class SrvPropSerializer(serializers.Serializer):
    index = serializers.ChoiceField(choices=["businesscontinuity", "inventory"])
    filters = serializers.DictField(required=True, child=serializers.ListField(child=serializers.CharField()))
    fields = serializers.ListField(child=serializers.CharField(), required=False)
    excludefields = serializers.ListField(child=serializers.CharField(), required=False)
    format = serializers.ChoiceField(choices=["json", "csv"], required=False, default="json")
    unify = serializers.ListField(child=serializers.CharField(), required=False)
    groupedby = serializers.CharField(required=False)
    enrich = EnrichSerializer(required=False)


class DynamicFieldsModelSerializer(serializers.ModelSerializer):

    # A ModelSerializer that takes an additional `fields` argument that controls which fields should be displayed.

    def __init__(self, *args, **kwargs):
        # Don't pass the arg up to the superclass
        fields = kwargs.pop('fields', None)
        excludefields = kwargs.pop('excludefields', None)
        default_exclude = kwargs.pop('default_exclude', None)

        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)
                
        if default_exclude is not None:
            # Exclude default fields if `fields` are not provided
            for field_name in default_exclude:
                self.fields.pop(field_name, None)

        if excludefields is not None:
            # Drop any fields that are specified in the `excludefields` argument.
            for field_name in excludefields:
                self.fields.pop(field_name, None)

    class Meta:
        fields = '__all__'  # You can specify specific fields or leave '__all__'


class InventoryServerSerializer(DynamicFieldsModelSerializer):
    class Meta:
        model = InventoryServer
        fields = '__all__'


class BusinessContinuitySerializer(DynamicFieldsModelSerializer):
    priority_asset = serializers.CharField(source='server_unique.priority_asset')
    in_live_play = serializers.CharField(source='server_unique.in_live_play')
    action_during_lp = serializers.CharField(source='server_unique.action_during_lp')
    original_action_during_lp = serializers.CharField(source='server_unique.original_action_during_lp')
    cluster = serializers.CharField(source='server_unique.cluster')
    cluster_type = serializers.CharField(source='server_unique.cluster_type')

    class Meta:
        model = BCServer
        fields = [
            'SERVER_ID',
            'ITCONTINUITY_LEVEL',
            'DAP_NAME',
            'DAP_AUID',
            'DATACENTER',
            'TECH_FAMILY',
            'MACHINE_TYPE',
            'VM_TYPE',
            'AFFINITY',
            'DATABASE_TECHNO',
            'DATABASE_DB_CI',
            'VITAL_LEVEL',
            'SUPPORT_GROUP',
            'priority_asset',
            'in_live_play',
            'action_during_lp',
            'original_action_during_lp',
            'cluster',
            'cluster_type'
        ]
        
        #fields = '__all__' 
