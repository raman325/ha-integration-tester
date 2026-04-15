"""Update platform for Integration Tester."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import IntegrationTesterGitHubAPI
from .const import (
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    DATA_COMMIT_HASH,
    DATA_COMMIT_URL,
    DATA_IS_PART_OF_HA_CORE,
    DATA_REPO_NAME,
    DATA_REPO_OWNER,
    DOMAIN,
    ReferenceType,
)
from .coordinator import IntegrationTesterCoordinator
from .helpers import extract_integration
from .repairs import create_restart_required_issue

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[IntegrationTesterCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up update entity from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        async_add_entities: Callback to add entities.

    """
    # Only create update entity for branches and PRs, not commits
    if ReferenceType(entry.data[CONF_REFERENCE_TYPE]) == ReferenceType.COMMIT:
        return

    async_add_entities([IntegrationUpdateEntity(entry.runtime_data, entry)])


class IntegrationUpdateEntity(
    CoordinatorEntity[IntegrationTesterCoordinator], UpdateEntity
):
    """Update entity for tracking integration updates."""

    _attr_has_entity_name = True
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(
        self,
        coordinator: IntegrationTesterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the update entity.

        Args:
            coordinator: Data update coordinator.
            entry: Config entry.

        """
        super().__init__(coordinator)
        self._entry = entry
        self._domain = entry.data[CONF_INTEGRATION_DOMAIN]

        self.entity_description = UpdateEntityDescription(
            key="update",
            translation_key="update",
        )
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_title = self._domain  # Domain as title (name derived by coordinator)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    @property
    def installed_version(self) -> str | None:
        """Return the installed version (commit hash)."""
        commit = self._entry.data.get(CONF_INSTALLED_COMMIT, "")
        return commit[:7] if commit else None

    @property
    def latest_version(self) -> str | None:
        """Return the latest version (current head commit)."""
        if not self.coordinator.data:
            return self.installed_version
        commit = self.coordinator.data.get(DATA_COMMIT_HASH, "")
        return commit[:7] if commit else None

    @property
    def release_url(self) -> str | None:
        """Return URL to the release/commit."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(DATA_COMMIT_URL)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update.

        Args:
            version: Version to install (ignored, we always install latest).
            backup: Whether to backup (ignored).
            **kwargs: Additional arguments.

        """
        if not self.coordinator.data:
            return

        new_commit = self.coordinator.data.get(DATA_COMMIT_HASH, "")
        if not new_commit:
            return

        owner = self.coordinator.data.get(DATA_REPO_OWNER, "")
        repo = self.coordinator.data.get(DATA_REPO_NAME, "")

        # Download and extract
        session = async_get_clientsession(self.hass)
        token = self.hass.data.get(DOMAIN, {}).get("github_token")
        api = IntegrationTesterGitHubAPI(session, token)

        try:
            archive_data = await api.download_archive(owner, repo, new_commit)
            config_dir = Path(self.hass.config.config_dir)
            await self.hass.async_add_executor_job(
                extract_integration,
                config_dir,
                archive_data,
                self._domain,
                self.coordinator.data.get(DATA_IS_PART_OF_HA_CORE, False),
            )

            # Update installed commit in config entry
            await self.coordinator.async_update_installed_commit(new_commit)

            # Create restart required repair issue
            create_restart_required_issue(self.hass, self._entry, self._domain)

            # Refresh coordinator to update state
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error("Failed to install update for %s: %s", self._domain, err)
            raise
