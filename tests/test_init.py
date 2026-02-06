"""Tests for integration setup and cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.integration_tester import async_remove_entry
from custom_components.integration_tester.const import (
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_PART_OF_HA_CORE,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
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


class TestSetup:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_setup_entry_with_existing_commit(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        pr_response: dict[str, Any],
    ):
        """Test setup when commit is already installed."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Mock PR info response (aiogithubapi returns dict via generic())
            pr_response["merged"] = False
            pr_response["state"] = "open"
            mock_pr_response = create_mock_response(pr_response)
            mock_client.generic = AsyncMock(return_value=mock_pr_response)

            result = await hass.config_entries.async_setup(mock_config_entry.entry_id)

        assert result is True
        assert DOMAIN in hass.data
        assert mock_config_entry.runtime_data is not None

    @pytest.mark.asyncio
    async def test_setup_entry_fresh_install(
        self,
        hass: HomeAssistant,
        pr_response: dict[str, Any],
        tmp_path: Path,
    ):
        """Test setup when no commit is installed yet (fresh install)."""
        # Create entry without CONF_INSTALLED_COMMIT
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test (PR #1)",
            data={
                CONF_URL: "https://github.com/owner/repo/pull/1",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "test_domain",
                CONF_IS_PART_OF_HA_CORE: False,
                # No CONF_INSTALLED_COMMIT - triggers fresh install
            },
            unique_id="test_domain_fresh",
        )
        entry.add_to_hass(hass)

        # Create custom_components directory
        custom_components = tmp_path / "custom_components"
        custom_components.mkdir()

        with (
            patch(
                "custom_components.integration_tester.api.GitHubAPI"
            ) as mock_github_cls,
            patch("custom_components.integration_tester.extract_integration"),
            patch(
                "custom_components.integration_tester.create_restart_required_issue"
            ) as mock_restart_issue,
            patch.object(hass.config, "config_dir", str(tmp_path)),
        ):
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Mock PR info response
            pr_response["head"]["sha"] = "fresh_commit_sha"
            pr_response["merged"] = False
            pr_response["state"] = "open"
            mock_pr_response = create_mock_response(pr_response)

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return mock_pr_response
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            # Mock download_archive
            mock_download = AsyncMock(return_value=b"archive_data")
            with patch(
                "custom_components.integration_tester.IntegrationTesterGitHubAPI"
            ) as mock_api_cls:
                mock_api = MagicMock()
                mock_api.get_pr_info = AsyncMock(
                    return_value=MagicMock(head_sha="fresh_commit_sha")
                )
                mock_api.download_archive = mock_download
                mock_api_cls.return_value = mock_api

                result = await hass.config_entries.async_setup(entry.entry_id)

        assert result is True
        # Verify download was attempted
        mock_download.assert_called_once()
        # Verify restart issue was created
        mock_restart_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_entry_fresh_install_with_restart(
        self,
        hass: HomeAssistant,
        pr_response: dict[str, Any],
        tmp_path: Path,
    ):
        """Test setup with restart flag triggers restart instead of issue."""
        # Create entry without CONF_INSTALLED_COMMIT
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test (PR #1)",
            data={
                CONF_URL: "https://github.com/owner/repo/pull/1",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "test_restart",
                CONF_IS_PART_OF_HA_CORE: False,
            },
            unique_id="test_restart",
        )
        entry.add_to_hass(hass)

        # Set the restart flag (as the add service would)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["restart_after_install_test_restart"] = True

        # Create custom_components directory
        custom_components = tmp_path / "custom_components"
        custom_components.mkdir()

        # Register a mock homeassistant.restart service
        restart_called = []

        async def mock_restart_service(call):
            restart_called.append(True)

        hass.services.async_register("homeassistant", "restart", mock_restart_service)

        with (
            patch(
                "custom_components.integration_tester.api.GitHubAPI"
            ) as mock_github_cls,
            patch("custom_components.integration_tester.extract_integration"),
            patch(
                "custom_components.integration_tester.create_restart_required_issue"
            ) as mock_restart_issue,
            patch.object(hass.config, "config_dir", str(tmp_path)),
        ):
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Mock PR info response
            pr_response["head"]["sha"] = "fresh_commit_sha"
            pr_response["merged"] = False
            pr_response["state"] = "open"
            mock_pr_response = create_mock_response(pr_response)

            async def mock_generic(endpoint, **kwargs):
                if "/pulls/" in endpoint and "/files" not in endpoint:
                    return mock_pr_response
                return create_mock_response({})

            mock_client.generic = AsyncMock(side_effect=mock_generic)

            # Mock download_archive
            mock_download = AsyncMock(return_value=b"archive_data")
            with patch(
                "custom_components.integration_tester.IntegrationTesterGitHubAPI"
            ) as mock_api_cls:
                mock_api = MagicMock()
                mock_api.get_pr_info = AsyncMock(
                    return_value=MagicMock(head_sha="fresh_commit_sha")
                )
                mock_api.download_archive = mock_download
                mock_api_cls.return_value = mock_api

                result = await hass.config_entries.async_setup(entry.entry_id)

        assert result is True
        # Verify restart was called instead of issue
        assert len(restart_called) == 1
        mock_restart_issue.assert_not_called()


class TestRemoval:
    """Tests for async_remove_entry."""

    @pytest.mark.asyncio
    async def test_remove_entry_deletes_files(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        tmp_path: Path,
    ):
        """Test that removing config entry deletes integration files."""
        # Create mock integration directory
        custom_components = tmp_path / "custom_components"
        custom_components.mkdir()
        integration_dir = custom_components / "test_domain"
        integration_dir.mkdir()
        (integration_dir / "__init__.py").touch()

        with (
            patch.object(hass.config, "config_dir", str(tmp_path)),
            patch(
                "custom_components.integration_tester.async_create_notification"
            ) as mock_notification,
        ):
            await async_remove_entry(hass, mock_config_entry)

        # Verify directory was deleted
        assert not integration_dir.exists()

        # Verify notification was created
        mock_notification.assert_called_once()
        call_args = mock_notification.call_args
        assert "test_domain" in call_args.kwargs.get(
            "title", ""
        ) or "test_domain" in str(call_args)

    @pytest.mark.asyncio
    async def test_remove_entry_core_integration_message(
        self,
        hass: HomeAssistant,
        tmp_path: Path,
    ):
        """Test removal message differs for core integrations."""
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_URL: "https://github.com/home-assistant/core/pull/123",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "123",
                CONF_INTEGRATION_DOMAIN: "zwave_js",
                CONF_IS_PART_OF_HA_CORE: True,
            },
            unique_id="zwave_js",
        )

        custom_components = tmp_path / "custom_components"
        custom_components.mkdir()
        integration_dir = custom_components / "zwave_js"
        integration_dir.mkdir()

        with (
            patch.object(hass.config, "config_dir", str(tmp_path)),
            patch(
                "custom_components.integration_tester.async_create_notification"
            ) as mock_notification,
        ):
            await async_remove_entry(hass, entry)

        # Verify core-specific message
        mock_notification.assert_called_once()
        call_args = mock_notification.call_args
        # async_create_notification uses (hass, message, ...) positional args
        message = call_args[0][1]  # Second positional arg is the message
        assert "built-in" in message
        assert "zwave_js" in message

    @pytest.mark.asyncio
    async def test_remove_entry_skip_file_deletion(
        self,
        hass: HomeAssistant,
        tmp_path: Path,
    ):
        """Test removal with skip_file_deletion flag preserves files."""
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_URL: "https://github.com/owner/repo/pull/123",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "123",
                CONF_INTEGRATION_DOMAIN: "test_skip_delete",
            },
            unique_id="test_skip_delete",
        )

        custom_components = tmp_path / "custom_components"
        custom_components.mkdir()
        integration_dir = custom_components / "test_skip_delete"
        integration_dir.mkdir()
        (integration_dir / "__init__.py").touch()

        # Set the skip_file_deletion flag (as the remove service would)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][f"skip_file_deletion_{entry.entry_id}"] = True

        with (
            patch.object(hass.config, "config_dir", str(tmp_path)),
            patch(
                "custom_components.integration_tester.async_create_notification"
            ) as mock_notification,
        ):
            await async_remove_entry(hass, entry)

        # Files should still exist
        assert integration_dir.exists()

        # Verify skip message
        mock_notification.assert_called_once()
        call_args = mock_notification.call_args
        message = call_args[0][1]
        assert "left the integration files" in message
