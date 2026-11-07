"""Tests for the config, reauth and options flows."""

from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.azure_dns_updater.const import DOMAIN

from .conftest import (
    DISCOVERY_URL,
    TENANT,
    TOKEN_URL,
    USER_INPUT,
    ZONE_URL,
)


@pytest.fixture(autouse=True)
def no_setup():
    """Don't run the actual sync after a flow finishes."""
    with patch(
        "custom_components.azure_dns_updater.async_setup_entry", return_value=True
    ):
        yield


def mock_token(mock) -> None:
    """Mock a working token endpoint."""
    mock.post(TOKEN_URL, json={"access_token": "token", "expires_in": 3600})


def mock_discovery(mock) -> None:
    """Mock Azure's 401 response naming the tenant."""
    mock.get(
        DISCOVERY_URL,
        status=401,
        headers={
            "WWW-Authenticate": (
                f'Bearer authorization_uri="https://login.windows.net/{TENANT}", '
                'error="invalid_token"'
            )
        },
    )


async def submit(hass: HomeAssistant, user_input: dict):
    """Run the user step with the given input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_discovers_tenant_and_creates_entry(hass, aioclient_mock) -> None:
    """An empty tenant is looked up from the subscription."""
    mock_discovery(aioclient_mock)
    mock_token(aioclient_mock)
    aioclient_mock.get(ZONE_URL, json={"name": "example.com"})

    result = await submit(hass, {**USER_INPUT, "zone_name": " Example.com. "})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "example.com"
    assert result["data"]["tenant_id"] == TENANT
    assert result["data"]["zone_name"] == "example.com"


async def test_subdomain_title(hass, aioclient_mock) -> None:
    """A named record is shown with its full name."""
    mock_token(aioclient_mock)
    aioclient_mock.get(ZONE_URL, json={"name": "example.com"})

    result = await submit(
        hass, {**USER_INPUT, "tenant_id": TENANT, "record_name": "home"}
    )

    assert result["title"] == "home.example.com"


async def test_tenant_lookup_failure(hass, aioclient_mock) -> None:
    """A subscription that yields no tenant shows a field error."""
    aioclient_mock.get(DISCOVERY_URL, status=404)

    result = await submit(hass, USER_INPUT)

    assert result["errors"] == {"tenant_id": "tenant_not_found"}


@pytest.mark.parametrize(
    ("token_status", "zone_status", "error"),
    [
        (401, 200, "invalid_auth"),
        (400, 200, "invalid_auth"),
        (500, 200, "cannot_connect"),
        (200, 403, "forbidden"),
        (200, 404, "zone_not_found"),
        (200, 500, "cannot_connect"),
    ],
)
async def test_validation_errors(
    hass, aioclient_mock, token_status, zone_status, error
) -> None:
    """Azure failures are shown on the form."""
    aioclient_mock.post(
        TOKEN_URL,
        status=token_status,
        json={"access_token": "token", "expires_in": 3600, "error_description": "x"},
    )
    aioclient_mock.get(ZONE_URL, status=zone_status, json={})

    result = await submit(hass, {**USER_INPUT, "tenant_id": TENANT})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_already_configured(hass, aioclient_mock) -> None:
    """The same record can't be added twice."""
    mock_token(aioclient_mock)
    aioclient_mock.get(ZONE_URL, json={"name": "example.com"})

    await submit(hass, {**USER_INPUT, "tenant_id": TENANT})
    result = await submit(hass, {**USER_INPUT, "tenant_id": TENANT})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_secret(hass, entry, aioclient_mock) -> None:
    """Reauth stores the new secret once Azure accepts it."""
    mock_token(aioclient_mock)
    aioclient_mock.get(ZONE_URL, json={"name": "example.com"})
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"client_secret": "new-secret"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["client_secret"] == "new-secret"


async def test_reauth_rejected_keeps_secret(hass, entry, aioclient_mock) -> None:
    """A rejected secret isn't stored."""
    aioclient_mock.post(TOKEN_URL, status=401, json={"error_description": "x"})
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"client_secret": "bad"}
    )

    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["client_secret"] == "secret"


async def test_options(hass, entry) -> None:
    """Options are stored."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 10, "ttl": 60}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"update_interval": 10, "ttl": 60}
