# Azure DNS Updater for Home Assistant

Dynamic DNS for [Azure DNS](https://learn.microsoft.com/azure/dns/): keeps an A record pointing at your home's public IP address.

Based on the Python client in [frodehus/azure-dyndns](https://github.com/frodehus/azure-dyndns).

## Install

**HACS:** add this repository as a custom repository of type *Integration*, install it, then restart Home Assistant.

**Manually:** copy `custom_components/azure_dns_updater` into your Home Assistant `config/custom_components/` folder, then restart.

Requires Home Assistant 2025.8 or newer.

## Set up

### Azure

You need a service principal with the **DNS Zone Contributor** role on the zone:

```bash
az ad sp create-for-rbac --name home-assistant-dns --role "DNS Zone Contributor" \
  --scopes /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Network/dnsZones/<zone>
```

This prints the client ID (`appId`), client secret (`password`) and tenant ID (`tenant`).

If you create the secret in the Azure portal instead, copy the secret's **Value**. The **Secret ID** shown next to it won't work.

### Home Assistant

Go to **Settings > Devices & services > Add integration > Azure DNS Updater** and enter:

| Field | Example | Notes |
| --- | --- | --- |
| Subscription ID | `00000000-...` | |
| Resource group | `my-dns-rg` | |
| DNS zone | `example.com` | |
| Record name | `@` | `@` is the zone itself. Use a name such as `home` for `home.example.com`. |
| Client ID | `00000000-...` | |
| Client secret | | |
| Tenant ID | `00000000-...` | Optional, looked up from the subscription if empty. |

Add the integration once per record you want to manage. When you add another record, you can pick the credentials you've already entered and only fill in the zone. The service principal needs the DNS Zone Contributor role on each zone.

Under **Configure** you can change the check interval (default 5 minutes) and record TTL (default 300 seconds).

## What it does

At each interval the integration looks up your public IPv4 address and compares it to the record, writing to Azure only if the address or TTL differs. Failed checks are retried at the next interval.

| Entity | Description |
| --- | --- |
| Public IP | Your current public IPv4 address |
| DNS record IP | The address in the DNS record |
| Last DNS update | When this integration last changed the record |
| Sync now | Runs a check immediately |

The sensors become unavailable when a check fails, which you can use to trigger an alert.

When the client secret expires, Home Assistant asks you for a new one under **Settings > Devices & services**. You only need to enter it once: it's also saved for every other record that uses the same client ID.

## Things to know

- The record ends up with **exactly one address**. Any other addresses in that A record set are removed.
- Other record types, such as MX and TXT, aren't touched.
- Azure alias records are never overwritten. The check fails with an error instead.
- Only IPv4 (A records) is supported.
- Your public IP is looked up through `api.ipify.org`, falling back to `ifconfig.me` and `ipv4.icanhazip.com`.

## Development

```bash
uv venv --python 3.14
uv pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).
