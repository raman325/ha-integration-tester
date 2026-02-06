"""Tests for data coordinator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.integration_tester.const import (
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_PART_OF_HA_CORE,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DATA_COMMIT_HASH,
    DATA_PR_STATE,
    DOMAIN,
    PRState,
    ReferenceType,
)
from custom_components.integration_tester.coordinator import (
    IntegrationTesterCoordinator,
)

from .conftest import create_config_entry, create_mock_response


@pytest.fixture
def mock_config_entry(hass: HomeAssistant):
    """Create a mock config entry."""
    entry = create_config_entry(
        hass,
        domain=DOMAIN,
        title="Test (PR #1)",
        data={
            CONF_URL: "https://github.com/owner/repo/pull/1",
            CONF_REFERENCE_TYPE: ReferenceType.PR.value,
            CONF_REFERENCE_VALUE: "1",
            CONF_INTEGRATION_DOMAIN: "test_domain",
            CONF_INSTALLED_COMMIT: "abc123",
        },
        unique_id="test_domain",
    )
    entry.add_to_hass(hass)
    return entry


class TestCoordinator:
    """Tests for IntegrationTesterCoordinator."""

    async def test_fetch_pr_data(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        pr_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test fetching PR data."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Update PR response to match our test entry
            pr_response["head"]["sha"] = "new_commit_sha"
            pr_response["merged"] = False
            pr_response["state"] = "open"

            # aiogithubapi uses generic() which returns dict data
            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return create_mock_response(pr_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, mock_config_entry)

            with patch.object(
                coordinator, "_handle_pr_closed", new_callable=AsyncMock
            ) as mock_pr_closed:
                await coordinator.async_refresh()

            assert coordinator.data is not None
            assert coordinator.data[DATA_COMMIT_HASH] == "new_commit_sha"
            mock_pr_closed.assert_not_called()

    async def test_update_available(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        pr_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test update_available property."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            pr_response["head"]["sha"] = "new_commit_sha"
            pr_response["merged"] = False
            pr_response["state"] = "open"

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return create_mock_response(pr_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, mock_config_entry)
            await coordinator.async_refresh()

            # Installed commit is "abc123", current is "new_commit_sha"
            assert coordinator.update_available is True

    async def test_no_update_when_same_commit(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        pr_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test no update available when same commit."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            pr_response["head"]["sha"] = "abc123"
            pr_response["merged"] = False
            pr_response["state"] = "open"

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return create_mock_response(pr_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, mock_config_entry)
            await coordinator.async_refresh()

            assert coordinator.update_available is False

    async def test_pr_merged_triggers_notification(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        pr_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test merged PR triggers notification."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            pr_response["head"]["sha"] = "abc123"
            pr_response["state"] = "closed"
            pr_response["merged"] = True

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return create_mock_response(pr_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, mock_config_entry)

            with (
                patch(
                    "custom_components.integration_tester.coordinator.create_pr_closed_issue"
                ) as mock_create_issue,
                patch(
                    "custom_components.integration_tester.coordinator.is_repair_issue_acknowledged",
                    return_value=False,
                ),
                patch("homeassistant.components.persistent_notification.async_create"),
            ):
                await coordinator.async_refresh()

            mock_create_issue.assert_called_once()
            assert coordinator.data[DATA_PR_STATE] == PRState.MERGED.value

    async def test_fetch_branch_data(
        self,
        hass: HomeAssistant,
        branch_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test fetching branch data."""
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test (branch: main)",
            data={
                CONF_URL: "https://github.com/owner/repo/tree/main",
                CONF_REFERENCE_TYPE: ReferenceType.BRANCH.value,
                CONF_REFERENCE_VALUE: "main",
                CONF_INTEGRATION_DOMAIN: "test_domain",
                CONF_INSTALLED_COMMIT: "old_commit",
            },
            unique_id="test_domain_branch",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            async def mock_generic(endpoint, **kwargs):
                if "/branches/" in endpoint:
                    return create_mock_response(branch_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, entry)
            await coordinator.async_refresh()

            assert coordinator.data is not None
            assert (
                coordinator.data[DATA_COMMIT_HASH]
                == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
            )

    async def test_fetch_commit_data(
        self,
        hass: HomeAssistant,
        commit_response: dict[str, Any],
    ):
        """Test fetching commit data."""
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test (commit: abc123)",
            data={
                CONF_URL: "https://github.com/owner/repo",
                CONF_REFERENCE_TYPE: ReferenceType.COMMIT.value,
                CONF_REFERENCE_VALUE: "dbfc180aed0a16c253c1563023b069d5bf3ebcd3",
                CONF_INTEGRATION_DOMAIN: "test_domain",
                CONF_INSTALLED_COMMIT: "dbfc180aed0a16c253c1563023b069d5bf3ebcd3",
            },
            unique_id="test_domain_commit",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            async def mock_generic(endpoint, **kwargs):
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, entry)
            await coordinator.async_refresh()

            assert coordinator.data is not None
            assert (
                coordinator.data[DATA_COMMIT_HASH]
                == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
            )
            # Commit references don't have updates
            assert coordinator.update_available is False

    async def test_core_pr_integration_removed(
        self,
        hass: HomeAssistant,
        pr_response: dict[str, Any],
        commit_response: dict[str, Any],
    ):
        """Test core PR triggers issue when integration removed from diff."""
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test Core (PR #134000)",
            data={
                CONF_URL: "https://github.com/home-assistant/core",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "134000",
                CONF_INTEGRATION_DOMAIN: "hue",
                CONF_INSTALLED_COMMIT: "abc123",
                CONF_IS_PART_OF_HA_CORE: True,
            },
            unique_id="hue_core",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            pr_response["head"]["sha"] = "new_commit_sha"
            pr_response["merged"] = False
            pr_response["state"] = "open"

            # Return files that don't include our integration
            pr_files = [{"filename": "homeassistant/components/zwave_js/__init__.py"}]

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" in endpoint:
                    return create_mock_response(pr_files)
                if "/pulls/" in endpoint:
                    return create_mock_response(pr_response)
                if "/commits/" in endpoint:
                    return create_mock_response(commit_response)
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            coordinator = IntegrationTesterCoordinator(hass, entry)

            with (
                patch(
                    "custom_components.integration_tester.coordinator.create_integration_removed_issue"
                ) as mock_create_issue,
                patch(
                    "custom_components.integration_tester.coordinator.is_repair_issue_acknowledged",
                    return_value=False,
                ),
                patch("homeassistant.components.persistent_notification.async_create"),
            ):
                await coordinator.async_refresh()

            # Should create integration removed issue since hue not in diff
            mock_create_issue.assert_called_once()
