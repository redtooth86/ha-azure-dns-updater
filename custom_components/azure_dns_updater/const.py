"""Constants for the Azure DNS Updater integration."""

from typing import Final

DOMAIN: Final = "azure_dns_updater"

CONF_SUBSCRIPTION_ID: Final = "subscription_id"
CONF_RESOURCE_GROUP: Final = "resource_group"
CONF_ZONE_NAME: Final = "zone_name"
CONF_RECORD_NAME: Final = "record_name"
CONF_TENANT_ID: Final = "tenant_id"
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"

CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_TTL: Final = "ttl"

APEX_RECORD: Final = "@"
DEFAULT_UPDATE_INTERVAL: Final = 5  # minutes
DEFAULT_TTL: Final = 300  # seconds
