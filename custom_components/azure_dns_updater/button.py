"""Button for the Azure DNS Updater integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AzureDnsConfigEntry
from .entity import AzureDnsEntity

PARALLEL_UPDATES = 1

SYNC_NOW = ButtonEntityDescription(
    key="sync_now", translation_key="sync_now", icon="mdi:refresh"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AzureDnsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([AzureDnsSyncButton(entry.runtime_data, SYNC_NOW)])


class AzureDnsSyncButton(AzureDnsEntity, ButtonEntity):
    """Runs a sync immediately instead of waiting for the next interval."""

    @property
    def available(self) -> bool:
        """Stay pressable after a failed sync so it can be retried."""
        return True

    async def async_press(self) -> None:
        """Sync the DNS record."""
        await self.coordinator.async_refresh()
