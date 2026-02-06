"""Tests for XSS protection in Google OAuth callback."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


class TestXSSProtection:
    """Ensure user input is HTML-escaped in OAuth callback responses."""

    def test_error_param_is_escaped(self):
        client = TestClient(app, raise_server_exceptions=False)
        xss_payload = '<script>alert("xss")</script>'
        response = client.get(
            f"/api/v1/google/callback?error={xss_payload}"
        )

        assert response.status_code == 400
        # The raw script tag should NOT appear in the response
        assert "<script>" not in response.text
        # The escaped version should appear
        assert "&lt;script&gt;" in response.text
