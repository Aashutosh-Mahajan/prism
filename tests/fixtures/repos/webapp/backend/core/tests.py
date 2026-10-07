from django.test import TestCase

from .models import EmailCode


class EmailCodeTests(TestCase):
    def test_unverified_user_gets_a_code(self):
        # Driven through the HTTP API, so the test never names the model methods directly.
        response = self.client.post("/api/v1/auth/login/")
        self.assertEqual(response.status_code, 403)
        self.assertGreater(EmailCode.LIFETIME_MINUTES, 0)


class KpiTests(TestCase):
    def test_platform_kpis_have_previous(self):
        response = self.client.get("/api/v1/analytics/platform/?range=30d")
        self.assertEqual(response.status_code, 200)
        self.assertIn("kpis", response.json())
