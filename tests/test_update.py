"""Tests for update entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.integration_tester.const import (
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DATA_COMMIT_HASH,
    DATA_COMMIT_URL,
    DATA_IS_PART_OF_HA_CORE,
    DATA_REPO_NAME,
    DATA_REPO_OWNER,
    DOMAIN,
    ReferenceType,
)
from custom_components.integration_tester.update import (
    IntegrationUpdateEntity,
    async_setup_entry,
)

from .conftest import create_config_entry


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        DATA_COMMIT_HASH: "new_commit_sha_12345",
        DATA_COMMIT_URL: "https://github.com/owner/repo/commit/new_commit_sha_12345",
        DATA_REPO_OWNER: "owner",
        DATA_REPO_NAME: "repo",
        DATA_IS_PART_OF_HA_CORE: False,
    }
    coordinator.last_update_success = True
    coordinator.async_update_installed_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_pr_entry(hass: HomeAssistant):
    """Create a mock PR config entry."""
    entry = create_config_entry(
        hass,
        domain=DOMAIN,
        title="Test (PR #1)",
        data={
            CONF_URL: "https://github.com/owner/repo/pull/1",
            CONF_REFERENCE_TYPE: ReferenceType.PR.value,
            CONF_REFERENCE_VALUE: "1",
            CONF_INTEGRATION_DOMAIN: "test_domain",
            CONF_INSTALLED_COMMIT: "old_commit_sha_12345",
        },
        unique_id="test_domain",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_commit_entry(hass: HomeAssistant):
    """Create a mock commit config entry."""
    entry = create_config_entry(
        hass,
        domain=DOMAIN,
        title="Test (commit: abc123)",
        data={
            CONF_URL: "https://github.com/owner/repo/commit/abc123",
            CONF_REFERENCE_TYPE: ReferenceType.COMMIT.value,
            CONF_REFERENCE_VALUE: "abc123",
            CONF_INTEGRATION_DOMAIN: "test_domain",
            CONF_INSTALLED_COMMIT: "abc123",
        },
        unique_id="test_domain_commit",
    )
    entry.add_to_hass(hass)
    return entry


class TestUpdateEntitySetup:
    """Tests for update entity setup."""

    async def test_setup_creates_entity_for_pr(
        self, hass: HomeAssistant, mock_pr_entry, mock_coordinator
    ):
        """Test setup creates update entity for PR entries."""
        mock_pr_entry.runtime_data = mock_coordinator

        entities = []

        def add_entities(new_entities):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_pr_entry, add_entities)

        assert len(entities) == 1
        assert isinstance(entities[0], IntegrationUpdateEntity)

    async def test_setup_skips_entity_for_commit(
        self, hass: HomeAssistant, mock_commit_entry, mock_coordinator
    ):
        """Test setup does not create update entity for commit entries."""
        mock_commit_entry.runtime_data = mock_coordinator

        entities = []

        def add_entities(new_entities):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_commit_entry, add_entities)

        assert len(entities) == 0


class TestIntegrationUpdateEntity:
    """Tests for IntegrationUpdateEntity."""

    def test_installed_version(self, mock_coordinator, mock_pr_entry):
        """Test installed version returns short commit hash."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.installed_version == "old_com"

    def test_latest_version(self, mock_coordinator, mock_pr_entry):
        """Test latest version returns current commit hash."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.latest_version == "new_com"

    def test_latest_version_no_data(self, mock_coordinator, mock_pr_entry):
        """Test latest version falls back to installed when no data."""
        mock_coordinator.data = None
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.latest_version == entity.installed_version

    def test_release_url(self, mock_coordinator, mock_pr_entry):
        """Test release URL."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert (
            entity.release_url
            == "https://github.com/owner/repo/commit/new_commit_sha_12345"
        )

    def test_release_url_no_data(self, mock_coordinator, mock_pr_entry):
        """Test release URL when no data."""
        mock_coordinator.data = None
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.release_url is None

    def test_available(self, mock_coordinator, mock_pr_entry):
        """Test available property."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.available is True

        mock_coordinator.last_update_success = False
        assert entity.available is False

    def test_available_no_data(self, mock_coordinator, mock_pr_entry):
        """Test available when no data."""
        mock_coordinator.data = None
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.available is False

    def test_supported_features(self, mock_coordinator, mock_pr_entry):
        """Test supported features."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        assert entity.supported_features == UpdateEntityFeature.INSTALL

    async def test_async_install(
        self, hass: HomeAssistant, mock_coordinator, mock_pr_entry
    ):
        """Test async_install downloads and extracts update."""
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        entity.hass = hass
        hass.data[DOMAIN] = {"github_token": "test_token"}

        with (
            patch(
                "custom_components.integration_tester.update.IntegrationTesterGitHubAPI"
            ) as mock_api_cls,
            patch("custom_components.integration_tester.update.extract_integration"),
            patch(
                "custom_components.integration_tester.update.create_restart_required_issue"
            ) as mock_restart_issue,
        ):
            mock_api = MagicMock()
            mock_api.download_archive = AsyncMock(return_value=b"archive_data")
            mock_api_cls.return_value = mock_api

            await entity.async_install(version=None, backup=False)

        mock_api.download_archive.assert_called_once_with(
            "owner", "repo", "new_commit_sha_12345"
        )
        mock_coordinator.async_update_installed_commit.assert_called_once_with(
            "new_commit_sha_12345"
        )
        mock_restart_issue.assert_called_once()
        mock_coordinator.async_request_refresh.assert_called_once()

    async def test_async_install_no_data(
        self, hass: HomeAssistant, mock_coordinator, mock_pr_entry
    ):
        """Test async_install does nothing when no data."""
        mock_coordinator.data = None
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        entity.hass = hass

        with patch(
            "custom_components.integration_tester.update.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            await entity.async_install(version=None, backup=False)

        mock_api_cls.assert_not_called()

    async def test_async_install_no_commit(
        self, hass: HomeAssistant, mock_coordinator, mock_pr_entry
    ):
        """Test async_install does nothing when no current commit."""
        mock_coordinator.data = {DATA_COMMIT_HASH: ""}
        entity = IntegrationUpdateEntity(mock_coordinator, mock_pr_entry)
        entity.hass = hass

        with patch(
            "custom_components.integration_tester.update.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            await entity.async_install(version=None, backup=False)

        mock_api_cls.assert_not_called()
