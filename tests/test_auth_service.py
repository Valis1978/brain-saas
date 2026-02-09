"""Tests for auth_service.py - authorization logic."""
import pytest
from unittest.mock import patch


class TestIsAuthorized:
    """Test whitelist-based authorization."""

    @patch.dict("os.environ", {"WHITELISTED_USERS": "111,222,333"})
    def test_authorized_user(self):
        # Need to reimport to get fresh module with new env
        import importlib
        import app.services.auth_service as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.is_authorized("111") is True
        assert auth_mod.is_authorized("222") is True

    @patch.dict("os.environ", {"WHITELISTED_USERS": "111,222,333"})
    def test_unauthorized_user(self):
        import importlib
        import app.services.auth_service as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.is_authorized("999") is False

    @patch.dict("os.environ", {"WHITELISTED_USERS": ""})
    def test_empty_whitelist_allows_all(self):
        import importlib
        import app.services.auth_service as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.is_authorized("anyuser") is True

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_env_allows_all(self):
        import importlib
        import app.services.auth_service as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.is_authorized("anyuser") is True
