"""Base entity for the Azure DNS Updater integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AzureDnsCoordinator


class AzureDnsEntity(CoordinatorEntity[AzureDnsCoordinator]):
    """An entity belonging to one managed DNS record."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: AzureDnsCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Microsoft Azure",
            model="DNS record",
            entry_type=DeviceEntryType.SERVICE,
        )
