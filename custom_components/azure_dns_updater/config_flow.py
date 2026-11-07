"""Config flow for the Azure DNS Updater integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
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

SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SUBSCRIPTION_ID): str,
        vol.Required(CONF_RESOURCE_GROUP): str,
        vol.Required(CONF_ZONE_NAME): str,
        vol.Required(CONF_RECORD_NAME, default=APEX_RECORD): str,
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR,
        vol.Optional(CONF_TENANT_ID): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR})


class AzureDnsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Azure DNS Updater."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: AzureDnsConfigEntry,
    ) -> AzureDnsOptionsFlow:
        """Return the options flow."""
        return AzureDnsOptionsFlow()

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
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
                except AzureDnsError:
                    errors["base"] = "cannot_connect"

            if not errors:
                if error := await self._async_validate(data):
                    errors["base"] = error
                else:
                    zone = data[CONF_ZONE_NAME]
                    title = zone if record == APEX_RECORD else f"{record}.{zone}"
                    return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
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
