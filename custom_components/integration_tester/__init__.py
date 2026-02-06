"""Integration Tester - Download and install custom integrations from GitHub."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IntegrationTesterGitHubAPI
from .const import (
    CONF_GITHUB_TOKEN,
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_PART_OF_HA_CORE,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
)
from .coordinator import IntegrationTesterCoordinator
from .helpers import (
    extract_integration,
    integration_exists,
    parse_github_url,
    remove_integration,
)
from .repairs import (
    create_restart_required_issue,
    remove_download_failed_issue,
    remove_integration_removed_issue,
    remove_pr_closed_issue,
    remove_restart_required_issue,
)
from .storage import async_load_token

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.UPDATE]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Integration Tester integration."""
    hass.data.setdefault(DOMAIN, {})

    # Load token from storage so it's available for all config entries
    if token_from_storage := await async_load_token(hass):
        hass.data[DOMAIN][CONF_GITHUB_TOKEN] = token_from_storage

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Integration Tester from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Parse URL to get owner/repo (dynamic, may have changed)
    parsed = parse_github_url(entry.data[CONF_URL])
    owner = parsed.owner
    repo = parsed.repo

    domain = entry.data[CONF_INTEGRATION_DOMAIN]
    ref_type = ReferenceType(entry.data[CONF_REFERENCE_TYPE])

    # Get the commit to download
    session = async_get_clientsession(hass)
    token = hass.data[DOMAIN].get(CONF_GITHUB_TOKEN)
    api = IntegrationTesterGitHubAPI(session, token)

    # Determine the commit SHA to use
    ref_value = entry.data[CONF_REFERENCE_VALUE]
    installed_commit = entry.data.get(CONF_INSTALLED_COMMIT)

    if not installed_commit:
        # First time setup - need to download and install
        try:
            if ref_type == ReferenceType.PR:
                pr_info = await api.get_pr_info(owner, repo, int(ref_value))
                commit_sha = pr_info.head_sha
            elif ref_type == ReferenceType.BRANCH:
                branch_info = await api.get_branch_info(owner, repo, ref_value)
                commit_sha = branch_info.head_sha
            else:  # COMMIT
                commit_info = await api.get_commit_info(owner, repo, ref_value)
                commit_sha = commit_info.sha

            # Download and extract
            _LOGGER.info(
                "Downloading %s from %s/%s at %s", domain, owner, repo, commit_sha[:7]
            )
            archive_data = await api.download_archive(owner, repo, commit_sha)
            config_dir = Path(hass.config.config_dir)
            # Use config entry's is_part_of_ha_core flag (detects forks via API)
            # rather than parsed URL (only checks for home-assistant/core literally)
            is_core = entry.data.get(CONF_IS_PART_OF_HA_CORE, False)
            await hass.async_add_executor_job(
                extract_integration,
                config_dir,
                archive_data,
                domain,
                is_core,
            )

            # Update config entry with installed commit
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_INSTALLED_COMMIT: commit_sha},
            )

            # Create restart required issue
            create_restart_required_issue(hass, entry, domain)

        except Exception as err:
            _LOGGER.error("Failed to download integration %s: %s", domain, err)
            raise

    # Set up coordinator
    coordinator = IntegrationTesterCoordinator(hass, entry)

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Do initial refresh
    await coordinator.async_config_entry_first_refresh()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry."""
    domain = entry.data[CONF_INTEGRATION_DOMAIN]
    # Use config entry's is_part_of_ha_core flag (detects forks via API)
    # rather than parsed URL (only checks for home-assistant/core literally)
    is_core = entry.data.get(CONF_IS_PART_OF_HA_CORE, False)

    # Remove the integration files
    if integration_exists(hass, domain):
        await remove_integration(hass, domain)
        _LOGGER.info("Removed integration files for %s", domain)

    # Clean up repair issues
    remove_restart_required_issue(hass, domain)
    remove_pr_closed_issue(hass, domain)
    remove_integration_removed_issue(hass, domain)
    remove_download_failed_issue(hass, domain)

    # Create notification about removal
    if is_core:
        message = (
            f"Integration Tester removed the `{domain}` override by deleting "
            f"the custom version from `custom_components/`. After restart, "
            f"Home Assistant will use the built-in `{domain}` integration."
        )
    else:
        message = (
            f"Integration Tester removed `{domain}` by deleting the "
            f"integration from `custom_components/`. After restart, "
            f"Home Assistant will no longer recognize this integration and "
            f"existing config entries will stop working. Reinstall via HACS "
            f"or manually if needed."
        )

    async_create_notification(
        hass,
        message,
        title="Integration Tester: Integration Removed",
        notification_id=f"integration_tester_removed_{domain}",
    )
