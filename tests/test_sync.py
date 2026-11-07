"""Tests for the sync behaviour, the part that writes to public DNS."""

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.azure_dns_updater.api import (
    PUBLIC_IP_URLS,
    PublicIpError,
    async_get_public_ip,
    parse_public_ip,
)
from custom_components.azure_dns_updater.const import DOMAIN

from .conftest import PUBLIC_IP, RECORD_URL, TOKEN_URL, record_body


def puts(mock: AiohttpClientMocker) -> list:
    """Return the record writes made so far."""
    return [call for call in mock.mock_calls if call[0].upper() == "PUT"]


async def setup(hass: HomeAssistant, entry) -> None:
    """Set up the integration."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_in_sync_does_not_write(hass, entry, azure) -> None:
    """An up to date record is left alone."""
    azure.get(RECORD_URL, json=record_body(PUBLIC_IP))
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert not puts(azure)
    assert hass.states.get("sensor.example_com_public_ip").state == PUBLIC_IP
    assert hass.states.get("sensor.example_com_dns_record_ip").state == PUBLIC_IP


async def test_sync_button_runs_a_check(hass, entry, azure) -> None:
    """Pressing the button checks the record straight away."""
    azure.get(RECORD_URL, json=record_body(PUBLIC_IP))
    await setup(hass, entry)
    calls = azure.call_count

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.example_com_sync_now"},
        blocking=True,
    )

    assert azure.call_count > calls


async def test_changed_ip_writes_and_keeps_metadata(hass, entry, azure) -> None:
    """A stale record is replaced, preserving unrelated metadata."""
    azure.get(RECORD_URL, json=record_body("1.1.1.1", metadata={"owner": "kept"}))
    azure.put(
        RECORD_URL,
        json=record_body(PUBLIC_IP, metadata={"updated": "2026-01-02T03:04:05+00:00"}),
    )
    await setup(hass, entry)

    [write] = puts(azure)
    properties = write[2]["properties"]
    assert properties["ARecords"] == [{"ipv4Address": PUBLIC_IP}]
    assert properties["TTL"] == 300
    assert properties["metadata"]["owner"] == "kept"
    assert "updated" in properties["metadata"]
    assert (
        hass.states.get("sensor.example_com_last_dns_update").state
        == "2026-01-02T03:04:05+00:00"
    )


async def test_missing_record_is_created(hass, entry, azure) -> None:
    """A record that doesn't exist yet is created."""
    azure.get(RECORD_URL, status=404)
    azure.put(RECORD_URL, json=record_body(PUBLIC_IP))
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert len(puts(azure)) == 1


async def test_changed_ttl_writes(hass, entry, azure) -> None:
    """A record with the right IP but wrong TTL is rewritten."""
    azure.get(RECORD_URL, json=record_body(PUBLIC_IP, ttl=3600))
    azure.put(RECORD_URL, json=record_body(PUBLIC_IP))
    await setup(hass, entry)

    assert len(puts(azure)) == 1


async def test_alias_record_is_not_overwritten(hass, entry, azure) -> None:
    """An alias record must never be replaced by an A record."""
    azure.get(
        RECORD_URL,
        json={"properties": {"TTL": 300, "targetResource": {"id": "/some/resource"}}},
    )
    azure.put(RECORD_URL, json=record_body(PUBLIC_IP))
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not puts(azure)


async def test_expired_secret_starts_reauth(hass, entry, aioclient_mock) -> None:
    """A rejected secret asks the user for a new one."""
    aioclient_mock.post(
        TOKEN_URL,
        status=401,
        json={"error": "invalid_client", "error_description": "AADSTS7000222: expired"},
    )
    aioclient_mock.get(PUBLIC_IP_URLS[0], text=PUBLIC_IP)
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["step_id"] == "reauth_confirm"


async def test_azure_outage_retries(hass, entry, azure) -> None:
    """A temporary Azure failure retries without asking for credentials."""
    azure.get(RECORD_URL, status=503)
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_lookup_failure_never_writes(hass, entry, aioclient_mock) -> None:
    """If no public IP can be determined the record is left alone."""
    for url in PUBLIC_IP_URLS:
        aioclient_mock.get(url, text="<html>captive portal</html>")
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token", "expires_in": 3600})
    aioclient_mock.get(RECORD_URL, json=record_body("1.1.1.1"))
    aioclient_mock.put(RECORD_URL, json=record_body("<html>"))
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not puts(aioclient_mock)


@pytest.mark.parametrize(
    "text", ["2001:4860:4860::8888", "192.168.1.1", "100.64.0.1", "<html>", ""]
)
def test_parse_public_ip_rejects(text: str) -> None:
    """IPv6, private, CGNAT and non-address responses are rejected."""
    with pytest.raises(ValueError):
        parse_public_ip(text)


def test_parse_public_ip_strips_whitespace() -> None:
    """Trailing newlines from lookup services are removed."""
    assert parse_public_ip(f"{PUBLIC_IP}\n") == PUBLIC_IP


async def test_lookup_falls_back(aioclient_mock, hass) -> None:
    """A failed or unusable lookup moves on to the next service."""
    aioclient_mock.get(PUBLIC_IP_URLS[0], exc=aiohttp.ClientError())
    aioclient_mock.get(PUBLIC_IP_URLS[1], text="2001:4860:4860::8888")
    aioclient_mock.get(PUBLIC_IP_URLS[2], text=PUBLIC_IP)
    async with aioclient_mock.create_session(hass.loop) as session:
        assert await async_get_public_ip(session) == PUBLIC_IP


async def test_lookup_all_fail(aioclient_mock, hass) -> None:
    """All services failing raises an error."""
    for url in PUBLIC_IP_URLS:
        aioclient_mock.get(url, status=500)
    async with aioclient_mock.create_session(hass.loop) as session:
        with pytest.raises(PublicIpError):
            await async_get_public_ip(session)
