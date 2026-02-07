"""Services for Integration Tester."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
)
from .exceptions import InvalidGitHubURLError
from .helpers import parse_github_url

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD = "add"
SERVICE_LIST = "list"
SERVICE_REMOVE = "remove"

ATTR_URL = "url"
ATTR_DOMAIN = "domain"
ATTR_ENTRY_ID = "entry_id"
ATTR_OWNER_REPO = "owner_repo"
ATTR_OVERWRITE = "overwrite"
ATTR_RESTART = "restart"
ATTR_DELETE_FILES = "delete_files"

SERVICE_ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_URL): cv.string,
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional(ATTR_RESTART, default=False): cv.boolean,
    }
)

REMOVE_EXCLUSIVE_GROUP = "identifier"

SERVICE_REMOVE_SCHEMA = vol.All(
    cv.has_at_least_one_key(ATTR_DOMAIN, ATTR_URL, ATTR_OWNER_REPO, ATTR_ENTRY_ID),
    vol.Schema(
        {
            vol.Exclusive(ATTR_DOMAIN, REMOVE_EXCLUSIVE_GROUP): cv.string,
            vol.Exclusive(ATTR_URL, REMOVE_EXCLUSIVE_GROUP): cv.string,
            vol.Exclusive(ATTR_OWNER_REPO, REMOVE_EXCLUSIVE_GROUP): cv.string,
            vol.Exclusive(ATTR_ENTRY_ID, REMOVE_EXCLUSIVE_GROUP): cv.string,
            vol.Optional(ATTR_DELETE_FILES, default=True): cv.boolean,
        }
    ),
)


def _get_integration_tester_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Get all Integration Tester config entries."""
    return hass.config_entries.async_entries(DOMAIN)


def _find_entry_by_criteria(
    hass: HomeAssistant,
    *,
    domain: str | None = None,
    url: str | None = None,
    owner_repo: str | None = None,
    entry_id: str | None = None,
) -> ConfigEntry | None:
    """Find a config entry matching the given criteria.

    Only one criteria should be provided (enforced by vol.Exclusive in schema).
    Raises HomeAssistantError if multiple entries match (ambiguous criteria).
    """
    entries = _get_integration_tester_entries(hass)

    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    if domain:
        for entry in entries:
            if entry.data.get(CONF_INTEGRATION_DOMAIN) == domain:
                return entry
        return None

    if url:
        try:
            parsed = parse_github_url(url)
            target_owner_repo = f"{parsed.owner}/{parsed.repo}"
            target_ref_type = parsed.reference_type
            target_ref_value = parsed.reference_value
        except InvalidGitHubURLError:
            return None

        matches: list[ConfigEntry] = []
        for entry in entries:
            entry_url = entry.data.get(CONF_URL, "")
            try:
                entry_parsed = parse_github_url(entry_url)
                entry_owner_repo = f"{entry_parsed.owner}/{entry_parsed.repo}"

                # Match on owner/repo and optionally ref type/value
                if entry_owner_repo == target_owner_repo:
                    # If target has specific ref, check it matches
                    if target_ref_value:
                        entry_ref_type = entry.data.get(CONF_REFERENCE_TYPE)
                        entry_ref_value = entry.data.get(CONF_REFERENCE_VALUE)
                        if (
                            entry_ref_type == target_ref_type.value
                            and entry_ref_value == target_ref_value
                        ):
                            matches.append(entry)
                    else:
                        # No specific ref, match on owner/repo only
                        matches.append(entry)
            except InvalidGitHubURLError:
                continue

        return _check_unique_match(matches, "url")

    if owner_repo:
        # owner_repo format: "owner/repo"
        matches = []
        for entry in entries:
            entry_url = entry.data.get(CONF_URL, "")
            try:
                entry_parsed = parse_github_url(entry_url)
                entry_owner_repo = f"{entry_parsed.owner}/{entry_parsed.repo}"
                if entry_owner_repo == owner_repo:
                    matches.append(entry)
            except InvalidGitHubURLError as exc:
                _LOGGER.debug(
                    "Failed to parse URL '%s' for entry '%s': %s",
                    entry_url,
                    entry.entry_id,
                    exc,
                )
                continue

        return _check_unique_match(matches, "owner_repo")

    return None


def _check_unique_match(
    matches: list[ConfigEntry], criteria_name: str
) -> ConfigEntry | None:
    """Check that matches are unique and return the entry or raise an error."""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Multiple matches - ambiguous criteria
    domains = [e.data.get(CONF_INTEGRATION_DOMAIN, "unknown") for e in matches]
    raise HomeAssistantError(
        f"Multiple entries match the {criteria_name} criteria: {', '.join(domains)}. "
        f"Use 'domain' or 'entry_id' for unambiguous selection."
    )


async def async_handle_add(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the add service call."""
    url = call.data[ATTR_URL]
    overwrite = call.data[ATTR_OVERWRITE]
    restart = call.data[ATTR_RESTART]

    # Trigger config flow with import source
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "import"},
        data={"url": url, "overwrite": overwrite, "restart": restart},
    )

    if result.get("type") == "abort":
        reason = result.get("reason", "unknown")
        # Include description placeholders in error for better diagnostics
        placeholders = result.get("description_placeholders", {})
        if placeholders:
            details = ", ".join(f"{k}={v}" for k, v in placeholders.items())
            raise HomeAssistantError(f"Failed to add integration: {reason} ({details})")
        raise HomeAssistantError(f"Failed to add integration: {reason}")

    if result.get("type") == "form":
        # Flow requires user interaction (e.g., multiple integrations in core PR)
        errors = result.get("errors", {})
        if errors:
            error_msg = ", ".join(f"{k}: {v}" for k, v in errors.items())
            raise HomeAssistantError(f"Failed to add integration: {error_msg}")
        raise HomeAssistantError(
            "This URL requires additional configuration. Please use the UI to add it."
        )


async def async_handle_list(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Handle the list service call."""
    entries = _get_integration_tester_entries(hass)

    result = []
    for entry in entries:
        entry_url = entry.data.get(CONF_URL, "")
        try:
            parsed = parse_github_url(entry_url)
            owner_repo = f"{parsed.owner}/{parsed.repo}"
        except InvalidGitHubURLError as exc:
            _LOGGER.debug(
                "Failed to parse URL '%s' for entry '%s': %s",
                entry_url,
                entry.entry_id,
                exc,
            )
            owner_repo = "unknown"

        result.append(
            {
                "entry_id": entry.entry_id,
                "domain": entry.data.get(CONF_INTEGRATION_DOMAIN, ""),
                "url": entry_url,
                "owner_repo": owner_repo,
                "reference_type": entry.data.get(CONF_REFERENCE_TYPE, ""),
                "reference_value": entry.data.get(CONF_REFERENCE_VALUE, ""),
                "title": entry.title,
            }
        )

    return {"entries": result, "count": len(result)}


async def async_handle_remove(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the remove service call."""
    domain = call.data.get(ATTR_DOMAIN)
    url = call.data.get(ATTR_URL)
    owner_repo = call.data.get(ATTR_OWNER_REPO)
    entry_id = call.data.get(ATTR_ENTRY_ID)
    delete_files = call.data[ATTR_DELETE_FILES]

    # Schema validates exactly one is provided via vol.Exclusive + has_at_least_one_key

    entry = _find_entry_by_criteria(
        hass,
        domain=domain,
        url=url,
        owner_repo=owner_repo,
        entry_id=entry_id,
    )

    if not entry:
        raise HomeAssistantError("No matching config entry found")

    # Store flag to indicate whether async_remove_entry should delete files.
    # This is checked by async_remove_entry in __init__.py.
    # Note: Concurrent removes for the same entry are safe - the second call
    # would fail at _find_entry_by_criteria since the entry no longer exists.
    hass.data.setdefault(DOMAIN, {})
    flag_key = f"skip_file_deletion_{entry.entry_id}"
    hass.data[DOMAIN][flag_key] = not delete_files

    # Remove the config entry (triggers async_remove_entry callback)
    try:
        await hass.config_entries.async_remove(entry.entry_id)
    finally:
        # Ensure the flag is cleaned up even if async_remove fails
        hass.data[DOMAIN].pop(flag_key, None)


def async_register_services(hass: HomeAssistant) -> None:
    """Register Integration Tester services."""

    # Define async wrappers to properly capture hass and ensure handlers are awaited.
    # Using lambdas would return coroutines that HA treats as sync (never awaited).
    async def handle_add(call: ServiceCall) -> None:
        await async_handle_add(hass, call)

    async def handle_list(call: ServiceCall) -> ServiceResponse:
        return await async_handle_list(hass, call)

    async def handle_remove(call: ServiceCall) -> None:
        await async_handle_remove(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD,
        handle_add,
        schema=SERVICE_ADD_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST,
        handle_list,
        schema=None,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE,
        handle_remove,
        schema=SERVICE_REMOVE_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Integration Tester services."""
    hass.services.async_remove(DOMAIN, SERVICE_ADD)
    hass.services.async_remove(DOMAIN, SERVICE_LIST)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE)
