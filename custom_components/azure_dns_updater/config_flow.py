"""Config flow for the Azure DNS Updater integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AzureAuthError,
    AzureDnsClient,
    AzureDnsError,
    AzureForbiddenError,
    AzureNotFoundError,
    async_discover_tenant,
)
from .const import (
    APEX_RECORD,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_RECORD_NAME,
    CONF_RESOURCE_GROUP,
    CONF_SUBSCRIPTION_ID,
    CONF_TENANT_ID,
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    CONF_ZONE_NAME,
    DEFAULT_TTL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .coordinator import AzureDnsConfigEntry

CONF_CREDENTIALS = "credentials"
NEW_CREDENTIALS = "new"

SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

ZONE_FIELDS: dict[vol.Marker, Any] = {
    vol.Required(CONF_SUBSCRIPTION_ID): str,
    vol.Required(CONF_RESOURCE_GROUP): str,
    vol.Required(CONF_ZONE_NAME): str,
    vol.Required(CONF_RECORD_NAME, default=APEX_RECORD): str,
}
ZONE_SCHEMA = vol.Schema(ZONE_FIELDS)
MANUAL_SCHEMA = vol.Schema(
    {
        **ZONE_FIELDS,
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR,
        vol.Optional(CONF_TENANT_ID): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR})


def _credentials_key(data: Mapping[str, Any]) -> str:
    """Identify a service principal, which may be shared by several zones."""
    return f"{data[CONF_TENANT_ID]}_{data[CONF_CLIENT_ID]}".lower()


class AzureDnsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Azure DNS Updater."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._credentials: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: AzureDnsConfigEntry,
    ) -> AzureDnsOptionsFlow:
        """Return the options flow."""
        return AzureDnsOptionsFlow()

    @callback
    def _saved_credentials(self) -> dict[str, AzureDnsConfigEntry]:
        """Return one entry per service principal, preferring working ones."""
        saved: dict[str, AzureDnsConfigEntry] = {}
        for entry in self._async_current_entries(include_ignore=False):
            key = _credentials_key(entry.data)
            if key not in saved or entry.state is ConfigEntryState.LOADED:
                saved[key] = entry
        return saved

    async def _async_validate(self, data: Mapping[str, Any]) -> str | None:
        """Check the settings against Azure, returning an error key on failure."""
        client = AzureDnsClient(
            async_get_clientsession(self.hass),
            data[CONF_SUBSCRIPTION_ID],
            data[CONF_RESOURCE_GROUP],
            data[CONF_ZONE_NAME],
            data[CONF_RECORD_NAME],
            data[CONF_TENANT_ID],
            data[CONF_CLIENT_ID],
            data[CONF_CLIENT_SECRET],
        )
        try:
            await client.async_validate_zone()
        except AzureAuthError:
            return "invalid_auth"
        except AzureForbiddenError:
            return "forbidden"
        except AzureNotFoundError:
            return "zone_not_found"
        except AzureDnsError:
            return "cannot_connect"
        return None

    async def _async_create(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Validate the settings and create the entry, or fill in errors."""
        data = {key: value.strip() for key, value in user_input.items()}
        data[CONF_ZONE_NAME] = data[CONF_ZONE_NAME].rstrip(".").lower()
        record = data[CONF_RECORD_NAME].rstrip(".").lower() or APEX_RECORD
        data[CONF_RECORD_NAME] = record

        await self.async_set_unique_id(
            "_".join(
                (
                    data[CONF_SUBSCRIPTION_ID],
                    data[CONF_RESOURCE_GROUP],
                    data[CONF_ZONE_NAME],
                    record,
                )
            ).lower()
        )
        self._abort_if_unique_id_configured()

        if not data.get(CONF_TENANT_ID):
            try:
                data[CONF_TENANT_ID] = await async_discover_tenant(
                    async_get_clientsession(self.hass),
                    data[CONF_SUBSCRIPTION_ID],
                )
            except AzureNotFoundError:
                errors[CONF_TENANT_ID] = "tenant_not_found"
                return None
            except AzureDnsError:
                errors["base"] = "cannot_connect"
                return None

        if error := await self._async_validate(data):
            errors["base"] = error
            return None
        zone = data[CONF_ZONE_NAME]
        title = zone if record == APEX_RECORD else f"{record}.{zone}"
        return self.async_create_entry(title=title, data=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer saved credentials if there are any, otherwise ask for them."""
        saved = self._saved_credentials()
        if not saved:
            return await self.async_step_manual()
        if user_input is not None:
            if (key := user_input[CONF_CREDENTIALS]) == NEW_CREDENTIALS:
                return await self.async_step_manual()
            entry = saved[key]
            self._credentials = {
                field: entry.data[field]
                for field in (
                    CONF_SUBSCRIPTION_ID,
                    CONF_TENANT_ID,
                    CONF_CLIENT_ID,
                    CONF_CLIENT_SECRET,
                )
            }
            return await self.async_step_zone()

        choices = {
            key: f"Client {entry.data[CONF_CLIENT_ID]} (used by {entry.title})"
            for key, entry in saved.items()
        }
        choices[NEW_CREDENTIALS] = "Enter new credentials"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CREDENTIALS, default=next(iter(saved))): vol.In(
                        choices
                    )
                }
            ),
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask only for the zone, reusing saved credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if result := await self._async_create(
                {**self._credentials, **user_input}, errors
            ):
                return result
        return self.async_show_form(
            step_id="zone",
            data_schema=self.add_suggested_values_to_schema(
                ZONE_SCHEMA, user_input or self._credentials
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the zone and the credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if result := await self._async_create(user_input, errors):
                return result
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication, typically after the client secret expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new client secret."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            secret = {CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip()}
            if error := await self._async_validate({**entry.data, **secret}):
                errors["base"] = error
            else:
                # Zones sharing this service principal need the new secret too.
                # Reloading them also dismisses their own reauth prompts.
                key = _credentials_key(entry.data)
                for other in self._async_current_entries(include_ignore=False):
                    if other.entry_id != entry.entry_id and (
                        _credentials_key(other.data) == key
                    ):
                        self.hass.config_entries.async_update_entry(
                            other, data={**other.data, **secret}
                        )
                        self.hass.config_entries.async_schedule_reload(other.entry_id)
                return self.async_update_reload_and_abort(entry, data_updates=secret)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"name": entry.title},
            errors=errors,
        )


class AzureDnsOptionsFlow(OptionsFlowWithReload):
    """Handle update interval and TTL options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                    vol.Required(
                        CONF_TTL, default=options.get(CONF_TTL, DEFAULT_TTL)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=86400)),
                }
            ),
        )
