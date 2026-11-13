"""construct_query: same syntax and same rules in every app having its own copy of it."""
import ast
import importlib
import os

from django.apps import apps
from django.conf import settings
from django.db.models import Q
from django.test import SimpleTestCase, TestCase

from businesscontinuity.models import Server
from businesscontinuity.tests.base import make_server

MODULES = {
    'businesscontinuity': ['businesscontinuity.views'],
    'inventory': ['inventory.views', 'inventory.views_dbcache'],
    'applications': ['applications.views'],
    'reportapp': ['reportapp.views'],
    'discrepancies': ['discrepancies.views'],
    'hardware': ['hardware.views'],
    'storage': ['storage.views'],
}


def all_construct_queries():
    """Yield (module name, construct_query), even for an app not installed here."""
    for app, modules in MODULES.items():
        installed = apps.is_installed(app) or any(c.name == app for c in apps.get_app_configs())
        for name in modules:
            if installed:
                yield name, importlib.import_module(name).construct_query
                continue
            path = os.path.join(settings.BASE_DIR, *name.split('.')) + '.py'
            with open(path, encoding='utf-8') as f:
                tree = ast.parse(f.read())
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'construct_query')
            space = {'Q': Q}
            exec(compile(ast.Module([node], []), path, 'exec'), space)
            yield name, space['construct_query']


class SyntaxTests(SimpleTestCase):

    def test_empty_terms_are_ignored(self):
        for name, construct_query in all_construct_queries():
            with self.subTest(name):
                self.assertEqual(construct_query('F', ['A', '', 'B']), construct_query('F', ['A', 'B']))
                self.assertEqual(construct_query('F', ['']), Q())
                self.assertEqual(construct_query('F', ['!A', '']), construct_query('F', ['!A']))
                self.assertEqual(construct_query('F', ['@A', '']), construct_query('F', ['@A']))

    def test_order_of_the_terms_does_not_matter(self):
        for name, construct_query in all_construct_queries():
            with self.subTest(name):
                self.assertEqual(construct_query('F', ['!B', 'A']), construct_query('F', ['A', '!B']))
                self.assertEqual(construct_query('F', ['!B', '@A', 'C']), construct_query('F', ['@A', 'C', '!B']))

    def test_excluded_exact_value_in_every_app(self):
        for name, construct_query in all_construct_queries():
            with self.subTest(name):
                self.assertEqual(construct_query('F', ['!@B']), construct_query('F', ['@!B']))
                self.assertEqual(construct_query('F', ['!@B']), Q() & (Q() & ~Q(F__iexact='B')))


class ResultTests(TestCase):
    """What the user actually gets, on real rows."""

    @classmethod
    def setUpTestData(cls):
        for hostname in ('PROD-TEST', 'PROD-X', 'DEV-TEST', 'DEV'):
            make_server(hostname)

    def select(self, terms):
        from businesscontinuity.views import construct_query
        return sorted(Server.objects.filter(construct_query('SERVER_ID', terms)).values_list('SERVER_ID', flat=True))

    def test_values_and_exclusions_in_any_order(self):
        for terms in (['prod', '!test'], ['!test', 'prod']):
            with self.subTest(terms=terms):
                self.assertEqual(self.select(terms), ['PROD-X'])
        for terms in (['prod', 'dev', '!test'], ['!test', 'dev', 'prod']):
            with self.subTest(terms=terms):
                self.assertEqual(self.select(terms), ['DEV', 'PROD-X'])

    def test_exclusions_alone(self):
        self.assertEqual(self.select(['!test']), ['DEV', 'PROD-X'])
        self.assertEqual(self.select(['!@dev']), ['DEV-TEST', 'PROD-TEST', 'PROD-X'])
        self.assertEqual(self.select(['!test', '!@dev']), ['PROD-X'])

    def test_exact_value_and_its_exclusion(self):
        self.assertEqual(self.select(['@DEV']), ['DEV'])
        self.assertEqual(self.select(['@DEV', '!@DEV']), [])
        self.assertEqual(self.select(['dev', '!@dev']), ['DEV-TEST'])

    def test_expand_still_works(self):
        self.assertEqual(self.select(['#@PROD-X']), ['PROD-X'])
        self.assertEqual(self.select(['#prod', '!test']), ['PROD-X'])
