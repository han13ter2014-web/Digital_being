"""Этап 8C: секреты остаются вне журналов и checkpoint."""

import os
from uuid import uuid4

import pytest

from src.core.external_credentials import (
    CredentialNotFound,
    MemoryCredentialStore,
    WindowsCredentialStore,
    credential_target,
    provider_api_key,
)


def test_memory_store_roundtrip_and_validation():
    store = MemoryCredentialStore()
    target = credential_target(" RUFP ")

    assert target == "DigitalBeing/rufp"
    assert store.get(target) is None
    store.set(target, "  fixture-secret  ")
    assert store.get(target) == "fixture-secret"
    assert store.delete(target) is True
    assert store.delete(target) is False

    with pytest.raises(ValueError):
        store.set(target, "")
    with pytest.raises(ValueError):
        credential_target("https://example.invalid")


def test_environment_has_precedence_and_store_is_fallback(monkeypatch):
    store = MemoryCredentialStore()
    store.set(credential_target("rufp"), "stored-fixture")
    monkeypatch.setenv("RUFP_API_KEY", "environment-fixture")

    assert provider_api_key("rufp", store=store) == "environment-fixture"
    monkeypatch.delenv("RUFP_API_KEY")
    assert provider_api_key("rufp", store=store) == "stored-fixture"


def test_missing_credential_error_contains_no_secret(monkeypatch):
    monkeypatch.delenv("RUFP_API_KEY", raising=False)
    with pytest.raises(CredentialNotFound) as caught:
        provider_api_key("rufp", store=MemoryCredentialStore())
    assert str(caught.value) == "API key is not configured for rufp"


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager")
def test_windows_credential_manager_roundtrip_with_fixture():
    store = WindowsCredentialStore()
    target = f"DigitalBeing/test-{uuid4()}"
    try:
        store.set(target, "not-a-real-api-key")
        assert store.get(target) == "not-a-real-api-key"
    finally:
        store.delete(target)
    assert store.get(target) is None
