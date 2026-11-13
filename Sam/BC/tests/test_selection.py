"""
Every mass operation must select exactly the servers the server list shows.
A filter forgotten in one of them once reset every server before a DR test.
"""
import copy
import json
import os
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

from django.urls import reverse

from businesscontinuity import bc_rules_views as rules
from businesscontinuity import views
from businesscontinuity.models import Server, ServerUnique
from businesscontinuity.tests.base import BCTestCase, make_server

LABELS_PATH = os.path.join(os.path.dirname(views.__file__), 'field_labels.json')
SERVER_FIELDS = {field.name for field in Server._meta.get_fields()}
UNIQUE_FIELDS = {field.name for field in ServerUnique._meta.get_fields()}


def load_labels():
    with open(LABELS_PATH, encoding='utf-8') as f:
        return json.load(f)


class SameSelectionEverywhereTests(BCTestCase):
    """For each filter of field_labels.json, compare the page with the bulk edit and the shared builder."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.labels = load_labels()
        cls.filters = []
        rows = {'A': {}, 'B': {}}
        values = {'A': {}, 'B': {}}
        for field, info in cls.labels['fields'].items():
            if not info.get('inputname') or field == 'SERVER_ID':
                continue
            for side in ('A', 'B'):
                value = f'{side}-{field}'[:100]
                if info.get('model_extra') == 'yes':
                    values[side][field] = value
                elif field in SERVER_FIELDS:
                    rows[side][field] = value
            cls.filters.append((field, info['inputname'], f'A-{field}'[:100]))
        make_server('HOST-A', rows=[rows['A']], **values['A'])
        make_server('HOST-B', rows=[rows['B']], **values['B'])
        make_server('HOST-C')
        cls.filters.append(('SERVER_ID', cls.labels['fields']['SERVER_ID']['inputname'], 'HOST-A'))

    def page_count(self, params):
        response = self.client.get(reverse('businesscontinuity:server_view'), params)
        self.assertEqual(response.status_code, 200)
        return response.context['unique_servers_count']

    def bulk_count(self, params):
        data = self.bulk(urlencode(params), annotation='X', dry_run='1').json()
        return data.get('servers', data)

    def builder_count(self, params):
        qs, _ = views._build_filtered_queryset(SimpleNamespace(user=self.user), urlencode(params))
        return qs.values('server_unique_id').distinct().count()

    def test_every_field_is_known_by_the_models(self):
        for field, info in self.labels['fields'].items():
            if info.get('inputname'):
                with self.subTest(field):
                    known = UNIQUE_FIELDS if info.get('model_extra') == 'yes' else SERVER_FIELDS
                    self.assertIn(field, known)

    def test_each_filter_selects_the_same_servers_everywhere(self):
        self.assertGreater(len(self.filters), 20)
        for field, input_name, value in self.filters:
            with self.subTest(field=field, input=input_name):
                params = {input_name: f'@{value}'}
                self.assertEqual(self.page_count(params), 1, 'the page itself must filter')
                self.assertEqual(self.bulk_count(params), 1, 'bulk edit')
                self.assertEqual(self.builder_count(params), 1, 'Apply BC Rules and DR reset')

    def test_a_new_or_renamed_field_is_filtered_everywhere_at_once(self):
        """The incident: a field renamed in field_labels.json must not be ignored by a mass operation."""
        renamed = copy.deepcopy(self.labels)
        renamed['fields']['annotation']['inputname'] = 'brandnewname'
        real_load = json.load

        def patched_load(f, *args, **kwargs):
            data = real_load(f, *args, **kwargs)
            return renamed if 'fields' in data and 'annotation' in data['fields'] else data

        params = {'brandnewname': '@A-annotation'}
        with mock.patch('businesscontinuity.views.json.load', side_effect=patched_load):
            self.assertEqual(self.page_count(params), 1)
            self.assertEqual(self.bulk_count(params), 1)
            self.assertEqual(self.builder_count(params), 1)


class CountSafetyTests(BCTestCase):
    """The page sends the number of servers it shows: every mass operation refuses another number."""

    def setUp(self):
        super().setUp()
        labels = copy.deepcopy(rules._load_field_labels())
        labels['bc_datacenter_siblings'] = {'TEST-DC-A': 'TEST-DC-B'}
        patcher = mock.patch.object(rules, '_load_field_labels', return_value=labels)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.a = make_server('SRV1', rows=[{'DATACENTER': 'TEST-DC-A', 'MACHINE_TYPE': 'HYPERVISOR'}])
        self.b = make_server('SRV2', rows=[{'DATACENTER': 'TEST-DC-A', 'MACHINE_TYPE': 'HYPERVISOR'}])

    def test_selection_mismatch_message(self):
        self.assertIsNone(views.selection_mismatch(2, '2'))
        self.assertIsNone(views.selection_mismatch(2, ''))
        self.assertIn('would target 2 servers, but the page shows 3', views.selection_mismatch(2, '3'))

    def test_apply_bc_rules(self):
        for count, ok in (('2', True), ('5', False)):
            with self.subTest(count=count):
                query = f'datacenter=%40TEST-DC-A&expected_servers={count}'
                response = self.client.get(reverse('businesscontinuity:bc_scope'), {'query': query})
                self.assertEqual(response.status_code == 200, ok, response.content)
                response = self.post_json('businesscontinuity:bc_start', {'query': query, 'sibling': None, 'rule_texts': {}})
                self.assertEqual(response.status_code == 200, ok, response.content)
        self.assertEqual(ServerUnique.objects.filter(action_during_lp='OLD ACTION').count(), 0)

    def test_apply_bc_rules_refused_writes_nothing(self):
        response = self.post_json('businesscontinuity:bc_start',
                                  {'query': 'datacenter=%40TEST-DC-A&expected_servers=9', 'sibling': None, 'rule_texts': {}})
        self.assertEqual(response.status_code, 400)
        self.assertIn('but the page shows 9', response.json()['error'])
        self.assertEqual(ServerUnique.objects.filter(action_during_lp='OLD ACTION').count(), 2)

    def test_dr_reset(self):
        preview = self.client.get(reverse('businesscontinuity:reset_dr_preview'),
                                  {'query': 'datacenter=%40TEST-DC-A', 'expected_servers': '3'})
        self.assertEqual(preview.status_code, 409)
        response = self.client.post(reverse('businesscontinuity:reset_dr'), {
            'confirm_token': 'CONFIRM', 'keep_history': '1', 'fields': 'annotation',
            'query': 'datacenter=%40TEST-DC-A', 'expected_servers': '3',
        })
        self.assertEqual(response.status_code, 409)
        self.assertIn('but the page shows 3', response.json()['error'])
        self.assertEqual(ServerUnique.objects.filter(annotation='OLD NOTE').count(), 2)
        response = self.client.post(reverse('businesscontinuity:reset_dr'), {
            'confirm_token': 'CONFIRM', 'keep_history': '1', 'fields': 'annotation',
            'query': 'datacenter=%40TEST-DC-A', 'expected_servers': '2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServerUnique.objects.filter(annotation='EMPTY').count(), 2)
