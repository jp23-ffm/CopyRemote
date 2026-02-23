import json

from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Server as InventoryServer
from api.views import SrvPropView


URL = '/api/srvprop/'


def post(client, payload):
    return client.post(
        URL,
        data=json.dumps(payload),
        content_type='application/json',
        HTTP_ACCEPT='application/json',
    )


# =============================================================================
# ⭐⭐⭐  Input validation — no DB needed, fast
# =============================================================================

class SrvPropValidationTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_missing_filters_returns_400(self):
        response = post(self.client, {"index": "inventory"})
        self.assertEqual(response.status_code, 400)

    def test_empty_filters_returns_400(self):
        response = post(self.client, {"index": "inventory", "filters": {}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("filters", str(response.data))

    def test_invalid_index_returns_400(self):
        response = post(self.client, {"index": "nonexistent", "filters": {"SERVER_ID": ["SRV001"]}})
        self.assertEqual(response.status_code, 400)
        # Serializer rejects unknown index before _resolve_index runs
        self.assertIn("index", str(response.data))

    def test_annotation_on_businesscontinuity_returns_400(self):
        response = post(self.client, {
            "index": "businesscontinuity",
            "filters": {"SERVER_ID": ["SRV001"], "ANNOTATION": ["test"]},
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("ANNOTATION", str(response.data))

    def test_annotation_in_fields_without_server_id_returns_400(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"REGION": ["EU"]},
            "fields": ["REGION", "ANNOTATION"],   # SERVER_ID missing
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("SERVER_ID", str(response.data))

    def test_enrich_same_index_returns_400(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"REGION": ["EU"]},
            "enrich": {"index": "inventory", "fields": ["OSSHORTNAME"]},
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("enrich", str(response.data))

    def test_invalid_filter_field_returns_400(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"NONEXISTENT_FIELD": ["value"]},
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid fields", str(response.data))


# =============================================================================
# ⭐⭐⭐  Internal helpers — pure unit tests, no HTTP
# =============================================================================

class BuildQObjectsTest(TestCase):

    def _build(self, filters):
        query_filter, exclude_filter, annotations = SrvPropView._build_q_objects(filters)
        return query_filter, exclude_filter, annotations

    def test_simple_value_produces_lower_annotation(self):
        _, _, annotations = self._build({"REGION": ["EU"]})
        self.assertIn("REGION_lower", annotations)

    def test_wildcard_produces_no_lower_annotation(self):
        _, _, annotations = self._build({"REGION": ["*EU*"]})
        self.assertNotIn("REGION_lower", annotations)

    def test_negation_goes_to_exclude_filter(self):
        query_filter, exclude_filter, _ = self._build({"REGION": ["!EU"]})
        # exclude_filter should be non-empty, query_filter empty
        self.assertFalse(bool(query_filter))
        self.assertTrue(bool(exclude_filter))

    def test_mixed_include_exclude(self):
        query_filter, exclude_filter, _ = self._build({"REGION": ["EU", "!US"]})
        self.assertTrue(bool(query_filter))
        self.assertTrue(bool(exclude_filter))

    def test_empty_values_produces_no_filter(self):
        query_filter, exclude_filter, annotations = self._build({"REGION": []})
        self.assertFalse(bool(query_filter))
        self.assertFalse(bool(exclude_filter))
        self.assertEqual(annotations, {})


class ValidateFiltersTest(TestCase):

    def setUp(self):
        self.view = SrvPropView()

    def test_valid_field_returns_no_errors(self):
        errors = self.view._validate_filters({"REGION": ["EU"]}, InventoryServer, "inventory")
        self.assertEqual(errors, [])

    def test_invalid_field_is_returned(self):
        errors = self.view._validate_filters({"NONEXISTENT": ["x"]}, InventoryServer, "inventory")
        self.assertIn("NONEXISTENT", errors)

    def test_multiple_invalid_fields_all_returned(self):
        errors = self.view._validate_filters(
            {"FAKEFIELD1": ["x"], "FAKEFIELD2": ["y"]}, InventoryServer, "inventory"
        )
        self.assertIn("FAKEFIELD1", errors)
        self.assertIn("FAKEFIELD2", errors)

    def test_valid_and_invalid_mixed(self):
        errors = self.view._validate_filters(
            {"REGION": ["EU"], "FAKEFIELD": ["x"]}, InventoryServer, "inventory"
        )
        self.assertNotIn("REGION", errors)
        self.assertIn("FAKEFIELD", errors)


# =============================================================================
# ⭐⭐  Happy path — query with actual data
# =============================================================================

class SrvPropQueryTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        InventoryServer.objects.create(SERVER_ID='SRV-EU-01', REGION='EU', COUNTRY='FR', LIVE_STATUS='ALIVE')
        InventoryServer.objects.create(SERVER_ID='SRV-EU-02', REGION='EU', COUNTRY='DE', LIVE_STATUS='ALIVE')
        InventoryServer.objects.create(SERVER_ID='SRV-US-01', REGION='US', COUNTRY='US', LIVE_STATUS='ALIVE')

    def test_response_has_count_and_results(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"SERVER_ID": ["SRV-EU-01"]},
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("count", data)
        self.assertIn("results", data)

    def test_filter_returns_matching_servers_only(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"REGION": ["EU"]},
            "fields": ["SERVER_ID", "REGION"],
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        server_ids = [r["SERVER_ID"] for r in data["results"]]
        self.assertIn("SRV-EU-01", server_ids)
        self.assertIn("SRV-EU-02", server_ids)
        self.assertNotIn("SRV-US-01", server_ids)

    def test_fields_parameter_restricts_columns(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"SERVER_ID": ["SRV-EU-01"]},
            "fields": ["SERVER_ID"],
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertIn("SERVER_ID", result)
        self.assertNotIn("REGION", result)
        self.assertNotIn("COUNTRY", result)

    def test_negation_excludes_matching_servers(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"REGION": ["!EU"]},
            "fields": ["SERVER_ID", "REGION"],
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        server_ids = [r["SERVER_ID"] for r in data["results"]]
        self.assertNotIn("SRV-EU-01", server_ids)
        self.assertNotIn("SRV-EU-02", server_ids)
        self.assertIn("SRV-US-01", server_ids)

    def test_wildcard_filter_matches_pattern(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"SERVER_ID": ["SRV-EU-*"]},
            "fields": ["SERVER_ID"],
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)

    def test_no_match_returns_empty_results(self):
        response = post(self.client, {
            "index": "inventory",
            "filters": {"REGION": ["MARS"]},
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])


# =============================================================================
# ⭐  ModelFieldsMappingView — basic checks
# =============================================================================

class ModelFieldsMappingTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_invalid_app_returns_404(self):
        response = self.client.get('/api/modelfieldsmapping/nonexistent/')
        self.assertEqual(response.status_code, 404)

    def test_valid_app_returns_mapping(self):
        response = self.client.get('/api/modelfieldsmapping/inventory/')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), dict)
        self.assertTrue(len(response.json()) > 0)
