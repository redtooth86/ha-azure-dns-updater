"""Minimal async client for the Azure DNS REST API and public IP lookup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

LOGIN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
MANAGEMENT_URL = "https://management.azure.com"
MANAGEMENT_SCOPE = f"{MANAGEMENT_URL}/.default"
DNS_API_VERSION = "2018-05-01"
SUBSCRIPTION_API_VERSION = "2020-01-01"

# Tried in order until one returns a usable address.
PUBLIC_IP_URLS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://ipv4.icanhazip.com",
)

TIMEOUT = aiohttp.ClientTimeout(total=20)
TOKEN_EXPIRY_MARGIN = timedelta(minutes=5)
TENANT_RE = re.compile(
    r'authorization_uri="https://[^/"]+/([0-9a-fA-F-]{36})"', re.IGNORECASE
)
UPDATED_BY = "azure-dns-updater (home-assistant)"


class AzureDnsError(Exception):
    """Base error, also raised for connection and unexpected API failures."""


class AzureAuthError(AzureDnsError):
    """The service principal credentials were rejected."""


class AzureForbiddenError(AzureDnsError):
    """The service principal lacks permission on the DNS zone."""


class AzureNotFoundError(AzureDnsError):
    """The subscription, resource group or zone does not exist."""


class AliasRecordError(AzureDnsError):
    """The record is an Azure alias, which must not be overwritten."""


class PublicIpError(AzureDnsError):
    """No lookup service returned a usable public IPv4 address."""


@dataclass(frozen=True)
class DnsRecord:
    """The parts of an Azure DNS A record set that we care about."""

    ips: tuple[str, ...] = ()
    ttl: int | None = None
    fqdn: str | None = None
    is_alias: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def last_updated(self) -> datetime | None:
        """Return when this integration last wrote the record, if known."""
        return dt_util.parse_datetime(self.metadata.get("updated", ""))


def parse_public_ip(text: str) -> str:
    """Return text as a public IPv4 address, or raise ValueError."""
    address = ipaddress.ip_address(text.strip())
    if address.version != 4 or not address.is_global:
        raise ValueError(f"{address} is not a public IPv4 address")
    return str(address)


async def async_get_public_ip(session: aiohttp.ClientSession) -> str:
    """Look up the public IPv4 address, session should be bound to IPv4."""
    for url in PUBLIC_IP_URLS:
        try:
            async with session.get(url, timeout=TIMEOUT) as response:
                response.raise_for_status()
                return parse_public_ip(await response.text())
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Public IP lookup via %s failed: %s", url, err)
    raise PublicIpError("Could not determine public IPv4 address")


async def async_discover_tenant(
    session: aiohttp.ClientSession, subscription_id: str
) -> str:
    """Find a subscription's tenant from Azure's unauthenticated 401 response."""
    url = f"{MANAGEMENT_URL}/subscriptions/{quote(subscription_id, safe='')}"
    try:
        async with session.get(
            url, params={"api-version": SUBSCRIPTION_API_VERSION}, timeout=TIMEOUT
        ) as response:
            header = response.headers.get("WWW-Authenticate", "")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AzureDnsError(f"Could not reach Azure: {err}") from err
    if match := TENANT_RE.search(header):
        return match.group(1)
    raise AzureNotFoundError("Could not find a tenant for this subscription")


class AzureDnsClient:
    """Reads and writes one A record set in an Azure DNS zone."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        subscription_id: str,
        resource_group: str,
        zone_name: str,
        record_name: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires = dt_util.utcnow()
        self._zone_url = (
            f"{MANAGEMENT_URL}/subscriptions/{quote(subscription_id, safe='')}"
            f"/resourceGroups/{quote(resource_group, safe='')}"
            f"/providers/Microsoft.Network/dnsZones/{quote(zone_name, safe='')}"
        )
        self._record_url = f"{self._zone_url}/A/{quote(record_name, safe='@*')}"

    async def _async_get_token(self) -> str:
        """Return a cached access token, requesting a new one when needed."""
        if self._token and dt_util.utcnow() < self._token_expires:
            return self._token
        try:
            async with self._session.post(
                LOGIN_URL.format(tenant=quote(self._tenant_id, safe="")),
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": MANAGEMENT_SCOPE,
                },
                timeout=TIMEOUT,
            ) as response:
                if response.status in (400, 401):
                    body = await response.json(content_type=None)
                    description = str(body.get("error_description", ""))
                    raise AzureAuthError(description.split("\r\n")[0])
                response.raise_for_status()
                body = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise AzureDnsError(f"Could not get Azure token: {err}") from err
        self._token = body["access_token"]
        self._token_expires = (
            dt_util.utcnow()
            + timedelta(seconds=int(body["expires_in"]))
            - TOKEN_EXPIRY_MARGIN
        )
        return self._token

    async def _async_request(
        self, method: str, url: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Make a management API request, returning None on 404."""
        token = await self._async_get_token()
        try:
            async with self._session.request(
                method,
                url,
                params={"api-version": DNS_API_VERSION},
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                timeout=TIMEOUT,
            ) as response:
                if response.status == 401:
                    self._token = None
                    raise AzureAuthError("Azure rejected the access token")
                if response.status == 403:
                    raise AzureForbiddenError(
                        "The service principal needs the DNS Zone Contributor "
                        "role on this zone"
                    )
                if response.status == 404:
                    return None
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise AzureDnsError(f"Azure request failed: {err}") from err

    async def async_validate_zone(self) -> None:
        """Check the credentials work and the zone exists."""
        if await self._async_request("GET", self._zone_url) is None:
            raise AzureNotFoundError("DNS zone not found")

    async def async_get_record(self) -> DnsRecord | None:
        """Return the A record set, or None if it doesn't exist yet."""
        body = await self._async_request("GET", self._record_url)
        return None if body is None else _parse_record(body)

    async def async_set_record(
        self, ip: str, ttl: int, metadata: Mapping[str, str]
    ) -> DnsRecord:
        """Create or replace the A record set with a single address."""
        body = await self._async_request(
            "PUT",
            self._record_url,
            {
                "properties": {
                    "TTL": ttl,
                    "ARecords": [{"ipv4Address": ip}],
                    "metadata": {
                        **metadata,
                        "updatedBy": UPDATED_BY,
                        "updated": dt_util.utcnow().isoformat(),
                    },
                }
            },
        )
        if body is None:
            raise AzureNotFoundError("DNS zone not found")
        return _parse_record(body)


def _parse_record(body: dict[str, Any]) -> DnsRecord:
    """Convert an Azure record set response to a DnsRecord."""
    properties = body.get("properties") or {}
    return DnsRecord(
        ips=tuple(
            record["ipv4Address"]
            for record in properties.get("ARecords") or ()
            if "ipv4Address" in record
        ),
        ttl=properties.get("TTL"),
        fqdn=properties.get("fqdn"),
        is_alias=bool((properties.get("targetResource") or {}).get("id")),
        metadata=properties.get("metadata") or {},
    )
