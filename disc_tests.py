import json

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in
from django.core.management import call_command
from datetime import timedelta

from monitor.signals import log_user_login
from discrepancies.models import DiscrepancyTracking, DiscrepancyAnnotation, AnalysisSnapshot, ImportStatus, ServerDiscrepancy
from discrepancies.views import _compute_days_open
from inventory.models import Server


class NoLoginLogMixin:
    """Disconnects the monitor login signal during tests to avoid NOT NULL constraint
    on client_hostname (DNS reverse lookup fails in test environment)."""

    def setUp(self):
        user_logged_in.disconnect(log_user_login)
        super().setUp()

    def tearDown(self):
        user_logged_in.connect(log_user_login)
        super().tearDown()


# ---------------------------------------------------------------------------
# _compute_days_open
# ---------------------------------------------------------------------------

class ComputeDaysOpenTest(TestCase):

    # --- guard cases ---

    def test_none_tracker_returns_empty(self):
        self.assertEqual(_compute_days_open(None), '')

    def test_empty_active_issues_returns_empty(self):
        t = DiscrepancyTracking(SERVER_ID='SRV001', active_issues={})
        self.assertEqual(_compute_days_open(t), '')

    # --- no filter: oldest_first_seen path ---

    def test_no_filter_uses_oldest_first_seen(self):
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={'REGION': {'first_seen': timezone.now().isoformat()}},
            oldest_first_seen=timezone.now() - timedelta(days=4),
        )
        self.assertEqual(_compute_days_open(t), 5)  # days + 1

    def test_no_filter_one_day_old(self):
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={'REGION': {'first_seen': timezone.now().isoformat()}},
            oldest_first_seen=timezone.now() - timedelta(days=0),
        )
        self.assertEqual(_compute_days_open(t), 1)

    # --- no filter: fallback to active_issues when oldest_first_seen is None ---

    def test_no_filter_fallback_to_active_issues(self):
        first_seen = (timezone.now() - timedelta(days=6)).isoformat()
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={'REGION': {'first_seen': first_seen}},
            oldest_first_seen=None,
        )
        self.assertEqual(_compute_days_open(t), 7)

    def test_no_filter_fallback_picks_max_of_multiple_fields(self):
        old = (timezone.now() - timedelta(days=9)).isoformat()
        recent = (timezone.now() - timedelta(days=2)).isoformat()
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={
                'REGION':  {'first_seen': old},
                'COUNTRY': {'first_seen': recent},
            },
            oldest_first_seen=None,
        )
        self.assertEqual(_compute_days_open(t), 10)  # max = old (9d) + 1

    # --- with filter: context-sensitive path ---

    def test_filter_returns_days_for_matching_field(self):
        old = (timezone.now() - timedelta(days=9)).isoformat()
        recent = (timezone.now() - timedelta(days=2)).isoformat()
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={
                'REGION':  {'first_seen': old},
                'COUNTRY': {'first_seen': recent},
            },
            oldest_first_seen=timezone.now() - timedelta(days=9),
        )
        # Filtered on COUNTRY only → 3, not 10
        self.assertEqual(_compute_days_open(t, filtered_fields={'COUNTRY'}), 3)

    def test_filter_picks_max_when_multiple_matches(self):
        old = (timezone.now() - timedelta(days=9)).isoformat()
        medium = (timezone.now() - timedelta(days=4)).isoformat()
        recent = (timezone.now() - timedelta(days=1)).isoformat()
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={
                'REGION':  {'first_seen': old},
                'COUNTRY': {'first_seen': medium},
                'CITY':    {'first_seen': recent},
            },
            oldest_first_seen=timezone.now() - timedelta(days=9),
        )
        # Filtered on REGION + COUNTRY → max = 9+1 = 10
        result = _compute_days_open(t, filtered_fields={'REGION', 'COUNTRY'})
        self.assertEqual(result, 10)

    def test_filter_no_match_falls_through_to_oldest_first_seen(self):
        first_seen = (timezone.now() - timedelta(days=5)).isoformat()
        t = DiscrepancyTracking(
            SERVER_ID='SRV001',
            active_issues={'REGION': {'first_seen': first_seen}},
            oldest_first_seen=timezone.now() - timedelta(days=5),
        )
        # Filter on a field not in active_issues → fallback to oldest_first_seen
        result = _compute_days_open(t, filtered_fields={'COUNTRY'})
        self.assertEqual(result, 6)


# ---------------------------------------------------------------------------
# DiscrepancyAnnotation.add_entry
# ---------------------------------------------------------------------------

class AnnotationAddEntryTest(TestCase):

    def setUp(self):
        self.ann = DiscrepancyAnnotation.objects.create(SERVER_ID='SRV001')

    def test_add_entry_sets_comment_and_assigned_to(self):
        self.ann.add_entry('problème réseau', 'alice', user=None)
        self.assertEqual(self.ann.comment, 'problème réseau')
        self.assertEqual(self.ann.assigned_to, 'alice')

    def test_add_entry_persists_to_db(self):
        self.ann.add_entry('sauvegardé', 'bob', user=None)
        fresh = DiscrepancyAnnotation.objects.get(SERVER_ID='SRV001')
        self.assertEqual(fresh.comment, 'sauvegardé')

    def test_add_entry_creates_history_entry(self):
        self.ann.add_entry('premier commentaire', 'alice', user=None)
        self.assertEqual(len(self.ann.history), 1)
        entry = self.ann.history[0]
        self.assertEqual(entry['comment'], 'premier commentaire')
        self.assertEqual(entry['assigned_to'], 'alice')
        self.assertEqual(entry['user'], 'Unknown')
        self.assertIn('date', entry)

    def test_add_entry_records_username(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user('testuser', password='x')
        self.ann.add_entry('avec user', 'alice', user=user)
        self.assertEqual(self.ann.history[0]['user'], 'testuser')

    def test_multiple_entries_append_history(self):
        self.ann.add_entry('first', 'alice', user=None)
        self.ann.add_entry('second', 'bob', user=None)
        self.ann.add_entry('third', 'carol', user=None)
        self.assertEqual(len(self.ann.history), 3)
        self.assertEqual(self.ann.comment, 'third')
        self.assertEqual(self.ann.assigned_to, 'carol')

    def test_get_history_display_sorted_newest_first(self):
        self.ann.add_entry('first', 'alice', user=None)
        self.ann.add_entry('second', 'bob', user=None)
        displayed = self.ann.get_history_display()
        self.assertEqual(displayed[0]['comment'], 'second')
        self.assertEqual(displayed[1]['comment'], 'first')

    def test_empty_history_returns_empty_list(self):
        self.assertEqual(self.ann.get_history_display(), [])


# ---------------------------------------------------------------------------
# ⭐⭐ Views — auth + smoke
# ---------------------------------------------------------------------------

def _make_user():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user('tester', password='x')


class ViewAuthTest(NoLoginLogMixin, TestCase):
    """Protected URLs redirect anonymous users and return 200 when logged in.
    Note: dashboard_view and trend_api_view are intentionally public (no @login_required).
    """

    PROTECTED_URLS = [
        ('discrepancies:servers', {}),
    ]

    PUBLIC_URLS = [
        ('discrepancies:dashboard', {}),
        ('discrepancies:trend_api', {}),
    ]

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user = _make_user()

    def test_anonymous_redirected(self):
        for name, kwargs in self.PROTECTED_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 302, f"{name} should redirect anonymous")
                self.assertIn('next=', response['Location'])

    def test_logged_in_gets_200(self):
        self.client.force_login(self.user)  # force_login bypasses auth signals (monitor DNS lookup)
        for name, kwargs in self.PROTECTED_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200, f"{name} should return 200")

    def test_public_urls_accessible_anonymously(self):
        for name, kwargs in self.PUBLIC_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200, f"{name} should be public")

    def test_annotation_get_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('discrepancies:edit_annotation', kwargs={'hostname': 'SRV001'}))
        self.assertEqual(response.status_code, 200)

    def test_annotation_anonymous_redirected(self):
        response = self.client.get(reverse('discrepancies:edit_annotation', kwargs={'hostname': 'SRV001'}))
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# ⭐⭐ analyze_discrepancies command
# ---------------------------------------------------------------------------

class AnalyzeCommandTest(TestCase):

    def _make_server(self, server_id, **kwargs):
        defaults = dict(
            LIVE_STATUS='ALIVE', OSSHORTNAME='RHEL8', OSFAMILY='Linux',
            MACHINE_TYPE='VIRTUAL', MANUFACTURER='VMware',
            COUNTRY='FR', APP_AUID_VALUE='APP001', APP_NAME_VALUE='MyApp',
            REGION='EU', CITY='Paris', INFRAVERSION='IV1',
            IPADDRESS='10.0.0.1', SNOW_STATUS='OPERATIONAL',
        )
        defaults.update(kwargs)
        return Server.objects.create(SERVER_ID=server_id, **defaults)

    def test_runs_on_empty_db(self):
        """Command succeeds even with no servers."""
        call_command('analyze_discrepancies', verbosity=0)
        self.assertTrue(ImportStatus.objects.filter(success=True).exists())
        self.assertTrue(AnalysisSnapshot.objects.exists())

    def test_clean_server_creates_no_discrepancy(self):
        self._make_server('SRV-CLEAN')
        call_command('analyze_discrepancies', verbosity=0)
        self.assertFalse(ServerDiscrepancy.objects.filter(SERVER_ID='SRV-CLEAN').exists())
        self.assertFalse(DiscrepancyTracking.objects.filter(SERVER_ID='SRV-CLEAN').exists())

    def test_server_with_missing_field_creates_discrepancy(self):
        self._make_server('SRV-BAD', REGION=None)
        call_command('analyze_discrepancies', verbosity=0)
        self.assertTrue(ServerDiscrepancy.objects.filter(SERVER_ID='SRV-BAD').exists())

    def test_server_with_missing_field_creates_tracker(self):
        self._make_server('SRV-BAD', REGION=None)
        call_command('analyze_discrepancies', verbosity=0)
        tracker = DiscrepancyTracking.objects.filter(SERVER_ID='SRV-BAD').first()
        self.assertIsNotNone(tracker)
        self.assertIn('REGION', tracker.active_issues)

    def test_import_status_records_server_count(self):
        self._make_server('SRV-A', REGION=None)
        self._make_server('SRV-B', CITY=None)
        call_command('analyze_discrepancies', verbosity=0)
        status = ImportStatus.objects.filter(success=True).last()
        self.assertIn('2 servers with discrepancies', status.message)


# ---------------------------------------------------------------------------
# ⭐ Export views — HTTP-level only (no file assertions)
# ---------------------------------------------------------------------------

class ExportViewTest(NoLoginLogMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_get_returns_405(self):
        for filetype in ['xlsx', 'csv']:
            with self.subTest(filetype=filetype):
                response = self.client.get(reverse('discrepancies:export_to_file', kwargs={'filetype': filetype}))
                self.assertEqual(response.status_code, 405)

    def test_invalid_filetype_returns_400(self):
        response = self.client.post(
            reverse('discrepancies:export_to_file', kwargs={'filetype': 'pdf'}),
            data=json.dumps({'filters': {}, 'columns': ['SERVER_ID']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_post_returns_job_id(self):
        for filetype in ['xlsx', 'csv']:
            with self.subTest(filetype=filetype):
                response = self.client.post(
                    reverse('discrepancies:export_to_file', kwargs={'filetype': filetype}),
                    data=json.dumps({'filters': {}, 'columns': ['SERVER_ID']}),
                    content_type='application/json',
                )
                self.assertEqual(response.status_code, 200)
                data = json.loads(response.content)
                self.assertIn('job_id', data)

    def test_export_status_unknown_job_returns_pending(self):
        response = self.client.get(
            reverse('discrepancies:export_status', kwargs={'job_id': 'nonexistent', 'filetype': 'xlsx'})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'pending')

    def test_download_unknown_job_returns_404(self):
        response = self.client.get(
            reverse('discrepancies:download_export', kwargs={'job_id': 'nonexistent', 'filetype': 'xlsx'})
        )
        self.assertEqual(response.status_code, 404)
