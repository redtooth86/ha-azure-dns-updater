"""The Azure DNS Updater integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AzureDnsClient
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_RECORD_NAME,
    CONF_RESOURCE_GROUP,
    CONF_SUBSCRIPTION_ID,
    CONF_TENANT_ID,
    CONF_ZONE_NAME,
)
from .coordinator import AzureDnsConfigEntry, AzureDnsCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AzureDnsConfigEntry) -> bool:
    """Set up Azure DNS Updater from a config entry."""
    client = AzureDnsClient(
        async_get_clientsession(hass),
        entry.data[CONF_SUBSCRIPTION_ID],
        entry.data[CONF_RESOURCE_GROUP],
        entry.data[CONF_ZONE_NAME],
        entry.data[CONF_RECORD_NAME],
        entry.data[CONF_TENANT_ID],
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )
    coordinator = AzureDnsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AzureDnsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
