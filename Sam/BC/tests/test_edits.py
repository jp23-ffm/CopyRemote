"""Bulk edit, DR reset and single edit: what is written, and what the history says."""
from unittest import mock

from django.urls import reverse

from businesscontinuity.models import ServerUnique
from businesscontinuity.tests.base import BCTestCase, make_server


def reload(su):
    su.refresh_from_db()
    return su


class BulkEditTests(BCTestCase):

    def test_review_writes_nothing_and_counts_real_changes(self):
        a = make_server('SRV1')
        make_server('SRV2', priority_asset='YES')
        data = self.bulk('server=SRV1,SRV2', priority_asset='YES', dry_run='1').json()
        self.assertEqual(data['status'], 'preview')
        self.assertEqual((data['servers'], data['changed'], data['unchanged']), (2, 1, 1))
        self.assertEqual(data['lists']['changed'][0]['changes'], [{'field': 'priority_asset', 'old': 'NO', 'new': 'YES'}])
        self.assertEqual(reload(a).priority_asset, 'NO')

    def test_servers_are_counted_not_inventory_lines(self):
        make_server('SRV1', rows=[{'DATACENTER': 'A'}, {'DATACENTER': 'B'}])
        self.assertEqual(self.bulk('server=SRV1', annotation='NEW', dry_run='1').json()['servers'], 1)

    def test_only_real_changes_reach_the_history(self):
        changed = make_server('SRV1')
        same = make_server('SRV2', priority_asset='YES', action_during_lp='NEW')
        self.run_bulk('server=SRV1,SRV2', priority_asset='YES', action_during_lp='NEW')
        self.assertEqual(reload(changed).priority_asset, 'YES')
        self.assertEqual(reload(same).global_history, [])

    def test_a_dash_and_an_empty_text_mean_unchanged(self):
        su = make_server('SRV1')
        self.run_bulk('server=SRV1', priority_asset='-', in_live_play='-', cluster='-', annotation='NEW', action_during_lp='', cluster_type='')
        reload(su)
        self.assertEqual((su.priority_asset, su.action_during_lp, su.annotation, su.cluster_type), ('NO', 'OLD ACTION', 'NEW', 'OLD TYPE'))

    def test_back_to_empty_is_traced(self):
        su = make_server('SRV1')
        self.run_bulk('server=SRV1', action_during_lp='EMPTY', annotation='EMPTY')
        reload(su)
        self.assertEqual(su.action_during_lp, 'EMPTY')
        self.assertEqual(set(su.global_history[0]['changes']), {'action_during_lp', 'annotation'})
        self.assertIn('EMPTY', su.action_during_lp_history)

    def test_filters_limit_the_selection(self):
        make_server('SRV1')
        other = make_server('OTHER')
        self.run_bulk('server=SRV1', annotation='NEW')
        self.assertEqual(reload(other).annotation, 'OLD NOTE')

    def test_empty_term_in_the_query_does_not_widen_the_selection(self):
        make_server('SRV1')
        make_server('SRV2')
        other = make_server('OTHER')
        self.assertEqual(self.bulk('server=SRV1,,SRV2', annotation='NEW', dry_run='1').json()['servers'], 2)
        self.assertEqual(reload(other).annotation, 'OLD NOTE')

    def test_nothing_to_change_starts_no_job(self):
        make_server('SRV1', priority_asset='YES')
        data = self.bulk('server=SRV1', priority_asset='YES').json()
        self.assertEqual(data['status'], 'warning')
        self.assertNotIn('job_id', data)

    def test_invalid_choice_is_refused(self):
        su = make_server('SRV1')
        response = self.bulk('server=SRV1', priority_asset='WRONG')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(reload(su).priority_asset, 'NO')

    def test_too_long_value_is_refused(self):
        su = make_server('SRV1')
        response = self.bulk('server=SRV1', cluster_type='X' * 256)
        self.assertEqual(response.status_code, 400)
        self.assertIn('too long', response.json()['message'])
        self.assertEqual(reload(su).cluster_type, 'OLD TYPE')

    def test_servers_in_exception_are_left_alone_by_default(self):
        excepted = make_server('SRV1', bc_exception='YES')
        normal = make_server('SRV2')
        data = self.bulk('server=SRV1,SRV2', annotation='NEW', dry_run='1').json()
        self.assertEqual((data['changed'], data['unchanged'], data['skipped_exceptions']), (1, 0, 1))
        self.assertEqual(data['lists']['skipped_exceptions'], ['SRV1'])
        status = self.run_bulk('server=SRV1,SRV2', annotation='NEW')
        self.assertIn('1 in exception ignored', status['stats']['message'])
        self.assertEqual(reload(excepted).annotation, 'OLD NOTE')
        self.assertEqual(excepted.global_history, [])
        self.assertEqual(reload(normal).annotation, 'NEW')

    def test_option_includes_servers_in_exception(self):
        excepted = make_server('SRV1', bc_exception='YES')
        data = self.bulk('server=SRV1', annotation='NEW', include_exceptions='1', dry_run='1').json()
        self.assertEqual((data['changed'], data['exceptions'], data['skipped_exceptions']), (1, 1, 0))
        self.run_bulk('server=SRV1', annotation='NEW', include_exceptions='1')
        self.assertEqual(reload(excepted).annotation, 'NEW')

    def test_lifting_exceptions_needs_the_option(self):
        excepted = make_server('SRV1', bc_exception='YES')
        self.assertEqual(self.bulk('server=SRV1', bc_exception='NO').json()['status'], 'warning')
        self.run_bulk('server=SRV1', bc_exception='NO', include_exceptions='1')
        self.assertEqual(reload(excepted).bc_exception, 'NO')
        self.assertEqual(excepted.global_history[0]['changes'], {'bc_exception': {'old': 'YES', 'new': 'NO'}})

    def test_only_excepted_servers_selected_warns(self):
        make_server('SRV1', bc_exception='YES')
        data = self.bulk('server=SRV1', annotation='NEW').json()
        self.assertEqual(data['status'], 'warning')
        self.assertIn('1 server in exception ignored', data['message'])

    def test_selection_must_match_the_page(self):
        su = make_server('SRV1')
        make_server('SRV2')
        for dry_run in ('1', ''):
            with self.subTest(dry_run=dry_run):
                response = self.bulk('server=SRV1,SRV2', annotation='NEW', expected_servers='3', dry_run=dry_run)
                self.assertEqual(response.status_code, 409)
                self.assertIn('would target 2 servers, but the page shows 3', response.json()['message'])
        self.assertEqual(reload(su).annotation, 'OLD NOTE')
        self.assertEqual(self.bulk('server=SRV1,SRV2', annotation='NEW', expected_servers='2', dry_run='1').json()['servers'], 2)

    def test_exceptions_do_not_change_the_selection_count(self):
        make_server('SRV1', bc_exception='YES')
        make_server('SRV2')
        for include in ('', '1'):
            with self.subTest(include=include):
                data = self.bulk('server=SRV1,SRV2', annotation='NEW', expected_servers='2', include_exceptions=include, dry_run='1').json()
                self.assertEqual((data['status'], data['servers']), ('preview', 2))
        status = self.run_bulk('server=SRV1,SRV2', annotation='NEW', expected_servers='2')
        self.assertIsNone(status['error'])

    def test_applied_changes_must_match_the_review(self):
        su = make_server('SRV1')
        other = make_server('SRV2')
        reviewed = self.bulk('server=SRV1,SRV2', annotation='NEW', dry_run='1').json()['fingerprint']
        ServerUnique.objects.filter(pk=other.pk).update(annotation='NEW')  # someone else edits in between
        response = self.bulk('server=SRV1,SRV2', annotation='NEW', fingerprint=reviewed)
        self.assertEqual(response.status_code, 409)
        self.assertIn('no longer the ones you reviewed', response.json()['message'])
        self.assertEqual(reload(su).annotation, 'OLD NOTE')
        fresh = self.bulk('server=SRV1,SRV2', annotation='NEW', dry_run='1').json()['fingerprint']
        self.run_bulk('server=SRV1,SRV2', annotation='NEW', fingerprint=fresh)
        self.assertEqual(reload(su).annotation, 'NEW')

    def test_failure_is_reported(self):
        su = make_server('SRV1')
        with mock.patch.object(ServerUnique.objects, 'bulk_update', side_effect=RuntimeError('simulated failure')):
            status = self.run_bulk('server=SRV1', annotation='NEW')
        self.assertIn('simulated failure', status['error'])
        self.assertEqual(reload(su).annotation, 'OLD NOTE')


class ResetTests(BCTestCase):

    def reset(self, hostname, keep_history, fields='annotation'):
        response = self.client.post(reverse('businesscontinuity:reset_dr'), {
            'confirm_token': 'CONFIRM', 'keep_history': keep_history, 'fields': fields, 'query': f'server=@{hostname}',
        })
        self.assertEqual(response.status_code, 200, response.content)
        return self.job_status('businesscontinuity:reset_dr_status', response.json()['job_id'])

    def old_history(self):
        return [{'date': '2026-01-01 10:00:00', 'user': 'x', 'fromsource': 'Bulk Edit', 'changes': {'cluster': {'old': 'NO', 'new': 'YES'}}}]

    def test_wipe_leaves_a_single_traced_entry(self):
        su = make_server('SRV1', annotation_history='old', action_during_lp_history='kept', global_history=self.old_history())
        self.reset('SRV1', '0')
        reload(su)
        self.assertEqual(su.annotation, 'EMPTY')
        self.assertEqual(len(su.global_history), 1)
        entry = su.global_history[0]
        self.assertEqual((entry['user'], entry['fromsource']), ('tester', 'DR Reset'))
        self.assertEqual(entry['changes']['annotation'], {'old': 'OLD NOTE', 'new': 'EMPTY'})
        self.assertIn('history_wiped', entry['changes'])
        self.assertFalse(su.annotation_history)
        self.assertEqual(su.action_during_lp_history, 'kept')

    def test_wipe_is_traced_even_with_nothing_to_reset(self):
        su = make_server('SRV1', annotation='EMPTY', global_history=self.old_history())
        self.reset('SRV1', '0')
        self.assertEqual(list(reload(su).global_history[0]['changes']), ['history_wiped'])

    def test_keeping_the_history(self):
        su = make_server('SRV1', annotation_history='old', global_history=self.old_history())
        self.reset('SRV1', '1')
        reload(su)
        self.assertEqual(len(su.global_history), 2)
        self.assertEqual(su.annotation_history, 'old')

    def test_exception_can_be_reset(self):
        su = make_server('SRV1', bc_exception='YES')
        self.reset('SRV1', '1', fields='bc_exception')
        self.assertEqual(reload(su).bc_exception, 'EMPTY')

    def test_other_servers_are_untouched(self):
        make_server('SRV1')
        other = make_server('OTHER')
        self.reset('SRV1', '0')
        self.assertEqual(reload(other).annotation, 'OLD NOTE')


class SingleEditTests(BCTestCase):

    def edit(self, su, note, **extra):
        return self.client.post(reverse('businesscontinuity:edit_server_info', kwargs={'server_unique_id': su.hostname}), {
            'priority_asset': su.priority_asset, 'in_live_play': su.in_live_play, 'action_during_lp': su.action_during_lp,
            'annotation': note, 'cluster': su.cluster, 'cluster_type': su.cluster_type,
            'referrer': '/businesscontinuity/', 'query': '', **extra,
        })

    def test_exception_is_edited_and_traced(self):
        su = make_server('SRV1')
        self.assertEqual(self.edit(su, su.annotation, bc_exception='YES').status_code, 302)
        reload(su)
        self.assertEqual(su.bc_exception, 'YES')
        self.assertEqual(su.global_history[-1]['changes']['bc_exception'], {'old': 'NO', 'new': 'YES'})

    def test_choices_left_empty_keep_the_stored_values(self):
        su = make_server('SRV1', priority_asset='EMPTY', in_live_play='YES', cluster='EMPTY')
        self.edit(su, 'NEW', priority_asset='', in_live_play='', cluster='')
        reload(su)
        self.assertEqual((su.priority_asset, su.in_live_play, su.cluster, su.annotation), ('EMPTY', 'YES', 'EMPTY', 'NEW'))
        changes = su.global_history[-1]['changes']
        self.assertEqual(changes['priority_asset']['new'], 'Not set or not modified')

    def test_choices_are_saved(self):
        su = make_server('SRV1')
        self.edit(su, su.annotation, priority_asset='YES', cluster='EMPTY')
        reload(su)
        self.assertEqual((su.priority_asset, su.cluster), ('YES', 'EMPTY'))

    def test_exception_kept_when_the_form_leaves_it_empty(self):
        su = make_server('SRV1', bc_exception='YES')
        self.edit(su, 'NEW', bc_exception='')
        self.assertEqual(reload(su).bc_exception, 'YES')

    def test_author_comes_from_the_session_not_from_the_form(self):
        su = make_server('SRV1')
        self.assertEqual(self.edit(su, 'NEW', loggedonuser='someone-else').status_code, 302)
        reload(su)
        self.assertEqual(su.annotation, 'NEW')
        self.assertEqual(su.global_history[-1]['user'], 'tester')
        self.assertNotIn('someone-else', su.annotation_history)
