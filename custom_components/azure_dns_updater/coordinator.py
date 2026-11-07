"""Keeps the Azure DNS record in sync with the public IP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import socket

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AliasRecordError,
    AzureAuthError,
    AzureDnsClient,
    AzureDnsError,
    DnsRecord,
    async_get_public_ip,
)
from .const import (
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_TTL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type AzureDnsConfigEntry = ConfigEntry[AzureDnsCoordinator]


@dataclass(frozen=True)
class AzureDnsData:
    """Result of the latest sync."""

    public_ip: str
    record: DnsRecord


class AzureDnsCoordinator(DataUpdateCoordinator[AzureDnsData]):
    """Compares the public IP to the DNS record and writes it when they differ."""

    config_entry: AzureDnsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AzureDnsConfigEntry,
        client: AzureDnsClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.client = client
        self._ttl: int = entry.options.get(CONF_TTL, DEFAULT_TTL)
        # A records only hold IPv4, so the lookup must not go out over IPv6.
        self._ipv4_session = async_get_clientsession(hass, family=socket.AF_INET)

    async def _async_update_data(self) -> AzureDnsData:
        """Update the record if the public IP or TTL has changed."""
        try:
            public_ip = await async_get_public_ip(self._ipv4_session)
            record = await self.client.async_get_record() or DnsRecord()
            if record.is_alias:
                raise AliasRecordError(
                    "This record is an Azure alias and won't be overwritten"
                )
            if record.ips != (public_ip,) or record.ttl != self._ttl:
                _LOGGER.info("Updating DNS record from %s to %s", record.ips, public_ip)
                record = await self.client.async_set_record(
                    public_ip, self._ttl, record.metadata
                )
        except AzureAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AzureDnsError as err:
            raise UpdateFailed(str(err)) from err
        return AzureDnsData(public_ip, record)
