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
        assert mock_config_entry.entry_id in hass.data[DOMAIN]


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
