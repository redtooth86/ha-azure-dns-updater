"""Sensors for the Azure DNS Updater integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AzureDnsConfigEntry, AzureDnsData
from .entity import AzureDnsEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AzureDnsSensorDescription(SensorEntityDescription):
    """Describes an Azure DNS Updater sensor."""

    value_fn: Callable[[AzureDnsData], str | datetime | None]


SENSORS = (
    AzureDnsSensorDescription(
        key="public_ip",
        translation_key="public_ip",
        icon="mdi:ip-network",
        value_fn=lambda data: data.public_ip,
    ),
    AzureDnsSensorDescription(
        key="record_ip",
        translation_key="record_ip",
        icon="mdi:dns",
        value_fn=lambda data: ", ".join(data.record.ips) or None,
    ),
    AzureDnsSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.record.last_updated,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AzureDnsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(
        AzureDnsSensor(entry.runtime_data, description) for description in SENSORS
    )


class AzureDnsSensor(AzureDnsEntity, SensorEntity):
    """A sensor reporting the state of the latest sync."""

    entity_description: AzureDnsSensorDescription

    @property
    def native_value(self) -> str | datetime | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)
