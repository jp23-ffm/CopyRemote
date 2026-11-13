"""Shared helpers for the businesscontinuity tests."""
import json
from importlib import import_module
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from accessrights.models import Permission, UserPermission
from businesscontinuity.models import Server, ServerUnique

CLASSIC_HEADER = 'hostname_unique;priority_asset;in_live_play;action_during_lp;annotation;cluster;cluster_type;bc_exception\r\n'
EXPORT_HEADER = 'SERVER_ID;DATACENTER;priority_asset;in_live_play;action_during_lp;annotation;cluster;cluster_type;bc_exception\r\n'
APP_HEADER = 'application_id;in_live_play\r\n'


class _ImmediateThread:
    """Runs the job in the test's own database transaction."""

    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def logged_client(user):
    """Return a client logged in without firing user_logged_in, which needs real request data."""
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store['_auth_user_id'] = str(user.pk)
    store['_auth_user_backend'] = settings.AUTHENTICATION_BACKENDS[0]
    store['_auth_user_hash'] = user.get_session_auth_hash()
    store.save()
    client = Client()
    client.cookies[settings.SESSION_COOKIE_NAME] = store.session_key
    return client


def make_server(hostname, rows=None, **values):
    """Create a ServerUnique and its inventory lines."""
    defaults = {'priority_asset': 'NO', 'in_live_play': 'NO', 'action_during_lp': 'OLD ACTION',
                'annotation': 'OLD NOTE', 'cluster': 'NO', 'cluster_type': 'OLD TYPE', 'bc_exception': 'NO', 'global_history': []}
    su = ServerUnique.objects.create(hostname=hostname, **{**defaults, **values})
    for row in rows or [{}]:
        Server.objects.create(server_unique=su, SERVER_ID=hostname, **row)
    return su


class BCTestCase(TestCase):
    """Logged-in editor, with background jobs run synchronously."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='tester', password='x')
        permission = Permission.objects.create(codename='businesscontinuity.edit', app='businesscontinuity', action='edit')
        UserPermission.objects.create(user=cls.user, permission=permission)

    def setUp(self):
        self.client = logged_client(self.user)
        immediate = SimpleNamespace(Thread=_ImmediateThread)
        for target in ('businesscontinuity.views.threading', 'businesscontinuity.bc_rules_views.threading'):
            patcher = mock.patch(target, immediate)
            patcher.start()
            self.addCleanup(patcher.stop)

    # Import page

    def upload(self, content, name='file.csv', import_type='server', **extra):
        raw = content if isinstance(content, bytes) else content.encode('utf-8')
        file = SimpleUploadedFile(name, raw, content_type='text/csv')
        return self.client.post(reverse('businesscontinuity:bulk_import_csv'),
                                {'csv_file': file, 'import_type': import_type, **extra})

    def preview(self, content, import_type='server'):
        response = self.upload(content, import_type=import_type, dry_run='1')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def run_import(self, content, name='file.csv', import_type='server'):
        """Launch an import and return its finished status."""
        response = self.upload(content, name=name, import_type=import_type)
        self.assertEqual(response.status_code, 200, response.content)
        return self.job_status('businesscontinuity:import_csv_status', response.json()['job_id'])

    def job_status(self, url_name, job_id):
        status = self.client.get(reverse(url_name, kwargs={'job_id': job_id})).json()
        self.assertTrue(status['done'], status)
        return status

    # Bulk edit

    def bulk(self, query, **values):
        return self.client.post(reverse('businesscontinuity:servers_bulk_update'), {'query': query, **values})

    def run_bulk(self, query, **values):
        response = self.bulk(query, **values)
        self.assertEqual(response.status_code, 200, response.content)
        return self.job_status('businesscontinuity:bulk_update_status', response.json()['job_id'])

    # JSON views

    def post_json(self, url_name, payload):
        return self.client.post(reverse(url_name), json.dumps(payload), content_type='application/json')
