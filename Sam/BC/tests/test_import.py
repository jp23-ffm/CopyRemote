"""CSV imports: server file, full export, applications, journal and report."""
import csv
import io
from unittest import mock

from django.test import Client
from django.urls import reverse

from businesscontinuity.models import CsvImportLog, Server, ServerUnique
from businesscontinuity.tests.base import APP_HEADER, CLASSIC_HEADER, EXPORT_HEADER, BCTestCase, make_server
from businesscontinuity import views


def reload(su):
    su.refresh_from_db()
    return su


class ServerImportTests(BCTestCase):

    def test_only_real_changes_are_written(self):
        changed = make_server('SRV1')
        same = make_server('SRV2')
        status = self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW ACTION;;;;\r\nSRV2;;;OLD ACTION;;;;\r\n')
        self.assertEqual((status['stats']['changed'], status['stats']['unchanged']), (1, 1))
        self.assertEqual(reload(changed).action_during_lp, 'NEW ACTION')
        self.assertIn('NEW ACTION', changed.action_during_lp_history)
        self.assertEqual(len(changed.global_history), 1)
        self.assertEqual(reload(same).global_history, [])
        self.assertFalse(same.action_during_lp_history)

    def test_empty_cell_leaves_the_field_alone(self):
        su = make_server('SRV1')
        self.run_import(CLASSIC_HEADER + 'SRV1;YES;;;;;;\r\n')
        reload(su)
        self.assertEqual((su.priority_asset, su.annotation, su.cluster_type), ('YES', 'OLD NOTE', 'OLD TYPE'))

    def test_values_are_cleaned(self):
        su = make_server('SRV1')
        self.run_import(CLASSIC_HEADER + 'SRV1; yes ;No; TEXT ;;EMPTY;;\r\n')
        reload(su)
        self.assertEqual((su.priority_asset, su.in_live_play, su.action_during_lp, su.cluster), ('YES', 'NO', 'TEXT', 'EMPTY'))

    def test_lower_case_stored_value_is_not_a_change(self):
        su = make_server('SRV1', priority_asset='yes')
        self.assertEqual(self.preview(CLASSIC_HEADER + 'SRV1;YES;;;;;;\r\n')['changed'], 0)
        self.assertEqual(reload(su).priority_asset, 'yes')

    def test_preview_writes_nothing_and_shows_old_and_new(self):
        su = make_server('SRV1')
        data = self.preview(CLASSIC_HEADER + 'SRV1;;;NEW ACTION;;;;\r\n')
        self.assertEqual(data['field_counts'], {'action_during_lp': 1})
        self.assertEqual(data['lists']['changed'][0]['changes'],
                         [{'field': 'action_during_lp', 'old': 'OLD ACTION', 'new': 'NEW ACTION'}])
        self.assertEqual(reload(su).action_during_lp, 'OLD ACTION')
        self.assertFalse(CsvImportLog.objects.exists())

    def test_invalid_value_ignores_the_whole_line(self):
        su = make_server('SRV1')
        data = self.preview(CLASSIC_HEADER + 'SRV1;WRONG;;NEW ACTION;;;;\r\n')
        self.assertEqual((data['changed'], data['invalid']), (0, 1))
        self.assertIn("invalid priority_asset value 'WRONG'", data['lists']['invalid'][0])
        self.assertIn('Line 2', data['lists']['invalid'][0])
        self.assertEqual(reload(su).action_during_lp, 'OLD ACTION')

    def test_too_long_value_ignores_the_whole_line(self):
        su = make_server('SRV1')
        ok = make_server('SRV2')
        data = self.preview(CLASSIC_HEADER + f'SRV1;;;NEW;;;{"X" * 256};\r\nSRV2;;;;;;{"X" * 255};\r\n')
        self.assertEqual((data['changed'], data['invalid']), (1, 1))
        self.assertIn('cluster_type is too long (max 255 characters)', data['lists']['invalid'][0])
        self.assertEqual(reload(su).action_during_lp, 'OLD ACTION')
        self.assertEqual(reload(ok).cluster_type, 'OLD TYPE')

    def test_long_text_without_limit_is_accepted(self):
        make_server('SRV1')
        self.assertEqual(self.preview(CLASSIC_HEADER + f'SRV1;;;{"X" * 1000};;;;\r\n')['changed'], 1)

    def test_server_listed_with_different_values_is_ignored(self):
        make_server('SRV1')
        data = self.preview(CLASSIC_HEADER + 'SRV1;;;FIRST;;;;\r\nSRV1;;;SECOND;;;;\r\n')
        self.assertEqual((data['changed'], data['invalid']), (0, 2))

    def test_identical_duplicate_is_written_once(self):
        su = make_server('SRV1')
        self.run_import(CLASSIC_HEADER + 'SRV1;;;SAME;;;;\r\nSRV1;;;SAME;;;;\r\n')
        self.assertEqual(reload(su).action_during_lp_history.count('SAME'), 1)

    def test_unknown_server_and_missing_hostname(self):
        data = self.preview(CLASSIC_HEADER + 'NOPE;;;X;;;;\r\n;;;Y;;;;\r\n')
        self.assertEqual((data['not_found'], data['no_hostname']), (1, 1))
        self.assertEqual(data['lists']['not_found'], ['NOPE'])

    def test_quoted_text_with_separator_and_line_break(self):
        su = make_server('SRV1')
        self.run_import(CLASSIC_HEADER + 'SRV1;;;"LINE 1; PART 2\nLINE 2";;;;\r\n')
        self.assertEqual(reload(su).action_during_lp, 'LINE 1; PART 2\nLINE 2')

    def test_refused_files(self):
        for label, content, message in (
            ('wrong header', 'a;b\r\n1;2\r\n', 'Header incorrect.'),
            ('wrong column count', CLASSIC_HEADER + 'SRV1;YES\r\n', '1 error detected.'),
            ('not utf-8', (CLASSIC_HEADER + 'SRV1;;;café;;;;\r\n').encode('latin-1'), 'This file is not UTF-8 encoded.'),
        ):
            with self.subTest(label):
                response = self.upload(content, dry_run='1')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], message)

    def test_utf8_bom_is_accepted(self):
        make_server('SRV1')
        self.assertEqual(self.preview(b'\xef\xbb\xbf' + (CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\n').encode())['changed'], 1)

    def test_lists_are_capped_but_counts_are_not(self):
        for i in range(3):
            make_server(f'SRV{i}')
        with mock.patch.object(views, 'IMPORT_LISTED_SERVERS_CAP', 2):
            data = self.preview(CLASSIC_HEADER + ''.join(f'SRV{i};;;NEW;;;;\r\n' for i in range(3)))
        self.assertEqual((data['changed'], len(data['lists']['changed'])), (3, 2))

    def test_failure_while_saving_reports_progress_and_can_be_resumed(self):
        servers = [make_server(f'SRV{i:03d}') for i in range(150)]
        content = CLASSIC_HEADER + ''.join(f'{s.hostname};;;NEW;;;;\r\n' for s in servers)
        real, calls = ServerUnique.objects.bulk_update, []

        def fail_second_batch(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('simulated failure')
            return real(*args, **kwargs)

        with mock.patch.object(ServerUnique.objects, 'bulk_update', side_effect=fail_second_batch):
            status = self.run_import(content)
        stats = status['stats']
        self.assertTrue(stats['failed'])
        self.assertEqual((stats['changed'], stats['total'], stats['not_saved']['count']), (100, 150, 50))
        self.assertEqual(ServerUnique.objects.filter(action_during_lp='NEW').count(), 100)
        self.assertEqual(self.preview(content)['changed'], 50)
        self.assertFalse(self.run_import(content)['stats']['failed'])
        self.assertEqual(ServerUnique.objects.filter(action_during_lp='NEW').count(), 150)


class ExceptionImportTests(BCTestCase):

    def test_file_is_the_source_and_exceptions_are_counted(self):
        excepted = make_server('SRV1', bc_exception='YES')
        make_server('SRV2')
        data = self.preview(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\nSRV2;;;NEW;;;;\r\n')
        self.assertEqual((data['changed'], data['exceptions']), (2, 1))
        self.assertEqual(data['lists']['exceptions'], ['SRV1'])
        self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\nSRV2;;;NEW;;;;\r\n')
        self.assertEqual(reload(excepted).action_during_lp, 'NEW')

    def test_the_file_can_set_and_lift_an_exception(self):
        su = make_server('SRV1')
        self.run_import(CLASSIC_HEADER + 'SRV1;;;;;;;yes\r\n')
        self.assertEqual(reload(su).bc_exception, 'YES')
        self.assertEqual(su.global_history[0]['changes'], {'bc_exception': {'old': 'NO', 'new': 'YES'}})
        data = self.preview(CLASSIC_HEADER + 'SRV1;;;;;;;NO\r\n')
        self.assertEqual((data['changed'], data['exceptions']), (1, 1))

    def test_invalid_exception_value_ignores_the_line(self):
        make_server('SRV1')
        data = self.preview(CLASSIC_HEADER + 'SRV1;;;NEW;;;;MAYBE\r\n')
        self.assertEqual((data['changed'], data['invalid']), (0, 1))
        self.assertIn("invalid bc_exception value 'MAYBE'", data['lists']['invalid'][0])

    def test_file_without_the_column_is_refused(self):
        old_header = CLASSIC_HEADER.replace(';bc_exception', '')
        response = self.upload(old_header + 'SRV1;;;NEW;;;\r\n', dry_run='1')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Header incorrect.')
        old_export = EXPORT_HEADER.replace(';bc_exception', '')
        self.assertEqual(self.upload(old_export + 'SRV1;A;;;NEW;;;\r\n', dry_run='1').status_code, 400)

    def test_application_import_counts_exceptions(self):
        make_server('SRV1', bc_exception='YES', rows=[{'DAP_AUID': 'A1'}])
        data = self.preview(APP_HEADER + 'A1;YES\r\n', import_type='application')
        self.assertEqual((data['changed'], data['exceptions']), (1, 1))

    def test_report_names_the_exceptions(self):
        make_server('SRV1', bc_exception='YES')
        status = self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\n')
        response = self.client.get(reverse('businesscontinuity:import_csv_report', kwargs={'log_id': status['stats']['log_id']}))
        self.assertIn('server in exception', response.content.decode())


class ExportImportTests(BCTestCase):

    def test_one_change_per_server_whatever_the_number_of_lines(self):
        su = make_server('SRV1', rows=[{'DATACENTER': 'A'}, {'DATACENTER': 'B'}])
        data = self.preview(EXPORT_HEADER + 'SRV1;A;YES;NO;NEW;OLD NOTE;NO;OLD TYPE;\r\nSRV1;B;YES;NO;NEW;OLD NOTE;NO;OLD TYPE;\r\n')
        self.assertTrue(data['is_export'])
        self.assertEqual((data['lines'], data['servers'], data['changed']), (2, 1, 1))
        self.assertEqual(reload(su).priority_asset, 'NO')

    def test_empty_cell_of_an_export_clears_the_field(self):
        su = make_server('SRV1')
        self.run_import(EXPORT_HEADER + 'SRV1;A;NO;NO;OLD ACTION;;NO;OLD TYPE;NO\r\n')
        reload(su)
        self.assertIsNone(su.annotation)
        self.assertEqual(su.global_history[0]['changes'], {'annotation': {'old': 'OLD NOTE', 'new': '(empty)'}})
        self.assertEqual(self.preview(EXPORT_HEADER + 'SRV1;A;NO;NO;OLD ACTION;;NO;OLD TYPE;NO\r\n')['changed'], 0)

    def test_lines_that_disagree_refuse_the_file(self):
        make_server('SRV1')
        response = self.upload(EXPORT_HEADER + 'SRV1;A;YES;NO;X;Y;NO;;\r\nSRV1;B;NO;NO;X;Y;NO;;\r\n', dry_run='1')
        self.assertEqual(response.status_code, 400)
        self.assertIn('conflicting line', response.json()['error'])
        self.assertIn('priority_asset', response.json()['detailed_errors'][0])


class ApplicationImportTests(BCTestCase):

    def preview_apps(self, lines):
        return self.preview(APP_HEADER + lines, import_type='application')

    def run_apps(self, lines):
        return self.run_import(APP_HEADER + lines, import_type='application')

    def test_yes_wins_on_the_same_application(self):
        su = make_server('SRV1', rows=[{'DAP_AUID': 'A1'}])
        self.run_apps('A1;NO\r\nA1;YES\r\n')
        self.assertEqual(reload(su).in_live_play, 'YES')

    def test_yes_wins_on_a_server_hosting_two_listed_applications(self):
        su = make_server('SRV1', rows=[{'DAP_AUID': 'A1'}, {'DAP_AUID': 'A2'}])
        data = self.preview_apps('A1;NO\r\nA2;YES\r\n')
        self.assertEqual(data['lists']['changed'][0]['changes'][0]['via'], 'A1=NO, A2=YES')
        self.run_apps('A1;NO\r\nA2;YES\r\n')
        self.assertEqual(reload(su).in_live_play, 'YES')

    def test_the_file_is_the_source_an_absent_application_has_no_influence(self):
        su = make_server('SRV1', in_live_play='YES', rows=[{'DAP_AUID': 'A1'}, {'DAP_AUID': 'A2'}])
        self.run_apps('A1;NO\r\n')
        self.assertEqual(reload(su).in_live_play, 'NO')

    def test_servers_of_other_applications_are_untouched(self):
        other = make_server('SRV2', in_live_play='YES', rows=[{'DAP_AUID': 'A2'}])
        make_server('SRV1', rows=[{'DAP_AUID': 'A1'}])
        self.run_apps('A1;YES\r\n')
        self.assertEqual(reload(other).in_live_play, 'YES')
        self.assertEqual(other.global_history, [])

    def test_same_file_twice_adds_no_history(self):
        su = make_server('SRV1', rows=[{'DAP_AUID': 'A1'}])
        self.run_apps('A1;YES\r\n')
        self.assertEqual(self.preview_apps('A1;YES\r\n')['changed'], 0)
        self.assertEqual(len(reload(su).global_history), 1)

    def test_ignored_lines_are_listed(self):
        make_server('SRV1', rows=[{'DAP_AUID': 'A1'}])
        data = self.preview_apps('NOPE;YES\r\nA1;MAYBE\r\n;YES\r\n')
        self.assertEqual((data['not_found'], data['invalid'], data['no_hostname'], data['changed']), (1, 1, 1, 0))
        self.assertEqual(data['lists']['not_found'], ['NOPE'])

    def test_refused_files(self):
        for label, content, message in (
            ('wrong column count', APP_HEADER + 'A1;YES;EXTRA\r\n', '1 error detected.'),
            ('not utf-8', (APP_HEADER + 'café;YES\r\n').encode('latin-1'), 'This file is not UTF-8 encoded.'),
        ):
            with self.subTest(label):
                response = self.upload(content, import_type='application', dry_run='1')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], message)


class JournalTests(BCTestCase):

    def test_import_is_journaled_with_its_author_and_counts(self):
        make_server('SRV1')
        make_server('SRV2')
        self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\nSRV2;;;OLD ACTION;;;;\r\nNOPE;;;X;;;;\r\n', name='my.csv')
        log = CsvImportLog.objects.get()
        self.assertEqual((log.username, log.filename, log.file_format), ('tester', 'my.csv', 'Server Import'))
        self.assertEqual((log.updated, log.unchanged, log.ignored, log.failed), (1, 1, 1, False))

    def test_export_and_application_formats(self):
        make_server('SRV1', rows=[{'DAP_AUID': 'A1'}])
        self.run_import(EXPORT_HEADER + 'SRV1;A;YES;NO;X;Y;NO;Z;\r\n')
        self.run_import(APP_HEADER + 'A1;YES\r\n', import_type='application')
        self.assertEqual(list(CsvImportLog.objects.order_by('id').values_list('file_format', flat=True)),
                         ['Server Export', 'Application Import'])

    def test_failure_is_journaled(self):
        make_server('SRV1')
        with mock.patch.object(ServerUnique.objects, 'bulk_update', side_effect=RuntimeError('simulated failure')):
            self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\n')
        log = CsvImportLog.objects.get()
        self.assertTrue(log.failed)
        self.assertIn('simulated failure', log.message)
        self.assertIn('not saved', log.report_csv)

    def test_report_has_every_outcome(self):
        make_server('SRV1')
        make_server('SRV2')
        status = self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\nSRV2;;;OLD ACTION;;;;\r\nNOPE;;;X;;;;\r\nSRV3;WRONG;;;;;;\r\n')
        response = self.client.get(reverse('businesscontinuity:import_csv_report', kwargs={'log_id': status['stats']['log_id']}))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.content.decode()), delimiter=';'))
        self.assertIn({'name': 'SRV1', 'status': 'updated', 'field': 'action_during_lp', 'old': 'OLD ACTION', 'new': 'NEW', 'detail': ''}, rows)
        self.assertEqual({(r['name'], r['status']) for r in rows},
                         {('SRV1', 'updated'), ('SRV2', 'already up to date'), ('NOPE', 'not found'), ('', 'line ignored')})

    def test_only_the_latest_reports_are_kept(self):
        make_server('SRV1')
        CsvImportLog.objects.bulk_create([
            CsvImportLog(username='old', filename=f'{i}.csv', file_format='Server Import', report_csv='BIG') for i in range(35)
        ])
        self.run_import(CLASSIC_HEADER + 'SRV1;;;NEW;;;;\r\n')
        self.assertEqual(CsvImportLog.objects.count(), 36)
        self.assertEqual(CsvImportLog.objects.exclude(report_csv='').count(), views.IMPORT_REPORTS_KEPT)

    def test_report_of_a_pruned_import_answers_404(self):
        log = CsvImportLog.objects.create(username='old', filename='a.csv', file_format='Server Import')
        response = self.client.get(reverse('businesscontinuity:import_csv_report', kwargs={'log_id': log.id}))
        self.assertEqual(response.status_code, 404)

    def test_report_needs_an_editor(self):
        log = CsvImportLog.objects.create(username='old', filename='a.csv', file_format='Server Import', report_csv='SECRET')
        response = Client().get(reverse('businesscontinuity:import_csv_report', kwargs={'log_id': log.id}))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b'SECRET', response.content)

    def test_upload_needs_an_editor(self):
        response = Client().post(reverse('businesscontinuity:bulk_import_csv'), {})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Server.objects.count(), 0)
