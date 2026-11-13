"""Apply BC Rules: scope, sibling reset, shared servers, identical reruns."""
import copy
from unittest import mock

from django.urls import reverse

from businesscontinuity import bc_rules_views as rules
from businesscontinuity.bc_rules_logic import DEFAULT_TEXTS, RULE_HYPERVISOR
from businesscontinuity.models import ServerUnique
from businesscontinuity.tests.base import BCTestCase, make_server

P1, P2, OTHER = 'TEST-DC-A', 'TEST-DC-B', 'TEST-DC-C'
QUERY = f'datacenter=%40{P1}'


def hypervisor(datacenter):
    return {'DATACENTER': datacenter, 'MACHINE_TYPE': 'HYPERVISOR'}


class BCRulesTests(BCTestCase):

    def setUp(self):
        super().setUp()
        # The real file holds site-specific names: tests bring their own pairs
        labels = copy.deepcopy(rules._load_field_labels())
        labels['bc_datacenter_siblings'] = {P1: P2, P2: P1}
        patcher = mock.patch.object(rules, '_load_field_labels', return_value=labels)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.in_scope = make_server('IN-SCOPE', rows=[hypervisor(P1)])
        self.sibling = make_server('ON-SIBLING', rows=[hypervisor(P2)])
        self.shared = make_server('ON-BOTH', rows=[hypervisor(P1), hypervisor(P2)])
        self.elsewhere = make_server('ELSEWHERE', rows=[hypervisor(OTHER)])

    def scope(self, query, **extra):
        return self.client.get(reverse('businesscontinuity:bc_scope'), {'query': query, **extra})

    def payload(self, sibling=P2, rule_texts=None, query=QUERY):
        return {'query': query, 'sibling': sibling, 'rule_texts': rule_texts or {}}

    def run_job(self, **kwargs):
        response = self.post_json('businesscontinuity:bc_start', self.payload(**kwargs))
        self.assertEqual(response.status_code, 200, response.content)
        return self.job_status('businesscontinuity:bc_job_status', response.json()['job_id'])

    def value(self, su):
        su.refresh_from_db()
        return su.action_during_lp

    def test_scope_refusals(self):
        for label, query, message in (
            ('no filter', '', 'required'),
            ('no datacenter', 'environment=PRD', 'required'),
            ('two datacenters', f'datacenter={P1},{P2}', 'exactly one'),
            ('no match', 'datacenter=NOPE', 'No servers'),
        ):
            with self.subTest(label):
                response = self.scope(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()['error'])

    def test_datacenter_outside_the_configuration_is_refused(self):
        with mock.patch.object(rules, '_load_field_labels', return_value={'bc_datacenter_siblings': {P2: P1}}):
            response = self.scope(QUERY)
        self.assertEqual(response.status_code, 400)
        self.assertIn('not configured', response.json()['error'])

    def test_scope_proposes_the_sibling_and_reports_shared_servers(self):
        data = self.scope(QUERY).json()
        self.assertEqual((data['datacenter'], data['default_sibling']), (P1, P2))
        self.assertIn('ON-BOTH', data['sibling']['shared'])

    def test_same_datacenter_as_sibling_is_refused(self):
        self.assertEqual(self.scope(QUERY, sibling=P1).status_code, 400)

    def test_preview_writes_nothing(self):
        response = self.post_json('businesscontinuity:bc_preview', self.payload())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.value(self.in_scope), 'OLD ACTION')
        self.assertEqual(self.value(self.sibling), 'OLD ACTION')

    def test_job_applies_the_rule_and_resets_the_sibling(self):
        status = self.run_job()
        self.assertIsNone(status['error'])
        self.assertEqual(self.value(self.in_scope), DEFAULT_TEXTS[RULE_HYPERVISOR])
        self.assertEqual(self.value(self.sibling), 'EMPTY')
        self.assertEqual(self.sibling.global_history[0]['fromsource'], 'BC Rules Reset')

    def test_server_on_both_sites_gets_the_rule_and_is_not_reset(self):
        self.run_job()
        self.assertEqual(self.value(self.shared), DEFAULT_TEXTS[RULE_HYPERVISOR])

    def test_other_datacenters_are_untouched(self):
        self.run_job()
        self.assertEqual(self.value(self.elsewhere), 'OLD ACTION')
        self.assertEqual(self.elsewhere.global_history, [])

    def test_without_sibling_nothing_is_reset(self):
        status = self.run_job(sibling=None)
        self.assertEqual(status['stats']['reset'], 0)
        self.assertEqual(self.value(self.sibling), 'OLD ACTION')

    def test_identical_rerun_writes_nothing(self):
        self.run_job(sibling=None)
        before = ServerUnique.objects.get(pk=self.in_scope.pk).global_history
        status = self.run_job(sibling=None)
        self.assertEqual(status['stats']['updated'], 0)
        self.assertEqual(ServerUnique.objects.get(pk=self.in_scope.pk).global_history, before)

    def test_exception_on_the_affected_site_is_ignored(self):
        excepted = make_server('EXCEPTED', bc_exception='YES', rows=[hypervisor(P1)])
        data = self.post_json('businesscontinuity:bc_preview', self.payload()).json()
        self.assertEqual(data['exceptions']['count'], 1)
        self.assertEqual(data['exceptions']['servers'], ['EXCEPTED'])
        self.assertEqual(data['total'], 2)
        status = self.run_job()
        self.assertEqual(status['stats']['exceptions']['count'], 1)
        self.assertEqual(self.value(excepted), 'OLD ACTION')
        self.assertEqual(excepted.global_history, [])
        self.assertEqual(self.value(self.in_scope), DEFAULT_TEXTS[RULE_HYPERVISOR])

    def test_exception_on_the_sibling_site_is_reset_and_announced(self):
        excepted = make_server('SIBLING-EXCEPTED', bc_exception='YES', rows=[hypervisor(P2)])
        data = self.post_json('businesscontinuity:bc_preview', self.payload()).json()
        self.assertEqual(data['sibling']['exceptions_reset'], {'count': 1, 'servers': ['SIBLING-EXCEPTED'], 'truncated': False})
        status = self.run_job()
        self.assertEqual(status['stats']['exceptions_reset'], 1)
        self.assertEqual(self.value(excepted), 'EMPTY')

    def test_only_exceptions_in_scope_still_resets_the_sibling(self):
        ServerUnique.objects.filter(pk__in=[self.in_scope.pk, self.shared.pk]).update(bc_exception='YES')
        status = self.run_job()
        self.assertIsNone(status['error'])
        self.assertEqual((status['stats']['total'], status['stats']['exceptions']['count']), (0, 2))
        self.assertEqual(self.value(self.sibling), 'EMPTY')
        self.assertEqual(self.value(self.in_scope), 'OLD ACTION')

    def test_blank_text_is_refused_and_empty_is_accepted(self):
        for label, blank in (('empty', ''), ('spaces', '   '), ('null', None)):
            with self.subTest(label):
                response = self.post_json('businesscontinuity:bc_start', self.payload(rule_texts={RULE_HYPERVISOR: blank}))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.value(self.in_scope), 'OLD ACTION')
        response = self.post_json('businesscontinuity:bc_preview', self.payload(rule_texts={RULE_HYPERVISOR: 'EMPTY'}))
        self.assertEqual(response.status_code, 200)

    def test_non_editor_cannot_start(self):
        with mock.patch.object(rules, 'is_editor', return_value=False):
            response = self.post_json('businesscontinuity:bc_start', self.payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.value(self.in_scope), 'OLD ACTION')
