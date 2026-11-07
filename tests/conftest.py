"""Shared fixtures for the Azure DNS Updater tests."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.azure_dns_updater.api import PUBLIC_IP_URLS
from custom_components.azure_dns_updater.const import DOMAIN

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
ZONE_URL = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
    "/resourceGroups/rg/providers/Microsoft.Network/dnsZones/example.com"
)
RECORD_URL = f"{ZONE_URL}/A/@"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
DISCOVERY_URL = f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
PUBLIC_IP = "8.8.4.4"

USER_INPUT = {
    "subscription_id": SUBSCRIPTION,
    "resource_group": "rg",
    "zone_name": "example.com",
    "record_name": "@",
    "client_id": "client",
    "client_secret": "secret",
}


def record_body(ip: str, ttl: int = 300, **properties) -> dict:
    """Return an Azure record set response."""
    return {
        "properties": {
            "TTL": ttl,
            "fqdn": "example.com.",
            "ARecords": [{"ipv4Address": ip}],
            **properties,
        }
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the integration."""


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a config entry for the apex record."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="example.com",
        unique_id="test",
        data={**USER_INPUT, "tenant_id": TENANT},
    )


@pytest.fixture
def azure(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a working token endpoint and public IP lookup."""
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token", "expires_in": 3600})
    aioclient_mock.get(PUBLIC_IP_URLS[0], text=PUBLIC_IP)
    return aioclient_mock
