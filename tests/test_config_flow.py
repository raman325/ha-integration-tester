"""Tests for config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.integration_tester.const import (
    CONF_GITHUB_TOKEN,
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
)
from custom_components.integration_tester.exceptions import GitHubAPIError
from custom_components.integration_tester.models import PRInfo, ResolvedReference

from .conftest import create_config_entry


def create_resolved_reference(
    *,
    owner: str = "raman325",
    repo: str = "lock_code_manager",
    reference_type: ReferenceType = ReferenceType.PR,
    reference_value: str = "1",
    is_part_of_ha_core: bool = False,
    commit_sha: str = "e937d69acdeab0dc5eba5dbbc3418d78f4459533",
    pr_info: PRInfo | None = None,
) -> ResolvedReference:
    """Create a ResolvedReference for testing."""
    return ResolvedReference(
        owner=owner,
        repo=repo,
        reference_type=reference_type,
        reference_value=reference_value,
        is_part_of_ha_core=is_part_of_ha_core,
        commit_sha=commit_sha,
        pr_info=pr_info,
    )


class TestConfigFlow:
    """Tests for config flow."""

    @pytest.mark.asyncio
    async def test_form_valid_pr_url(
        self,
        hass: HomeAssistant,
    ):
        """Test successful config flow with PR URL."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference to return ResolvedReference for external repo
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )

            # Mock HACS validation - file_exists for hacs.json
            mock_api.file_exists = AsyncMock(return_value=True)

            # Mock directory contents
            mock_api.get_directory_contents = AsyncMock(
                return_value=[{"name": "lock_code_manager", "type": "dir"}]
            )

            # Mock manifest content
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "lock_code_manager", "name": "Lock Code Manager"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "user"

            with patch(
                "custom_components.integration_tester.helpers.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {
                        "url": "https://github.com/raman325/lock_code_manager/pull/1",
                        "github_token": "test_token",
                    },
                )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "Lock Code Manager" in result["title"]
        assert "PR #1" in result["title"]
        # URL should be normalized (just owner/repo, no reference type/value)
        assert (
            result["data"][CONF_URL] == "https://github.com/raman325/lock_code_manager"
        )
        assert "/pull/" not in result["data"][CONF_URL]
        assert result["data"][CONF_REFERENCE_TYPE] == ReferenceType.PR.value
        assert result["data"][CONF_REFERENCE_VALUE] == "1"

    @pytest.mark.asyncio
    async def test_form_invalid_url(self, hass: HomeAssistant):
        """Test config flow with invalid URL."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            mock_api.validate_token = AsyncMock(return_value=True)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": "not-a-valid-url", "github_token": "test_token"},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"url": "invalid_url"}

    @pytest.mark.asyncio
    async def test_form_core_pr_single_integration(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow with core PR that modifies single integration."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference to return ResolvedReference for core repo
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference(
                    owner="home-assistant",
                    repo="core",
                    reference_type=ReferenceType.PR,
                    reference_value="134000",
                    is_part_of_ha_core=True,
                    commit_sha="63bc46580b3dcd930c1bf6839ba6ca2cc82d900f",
                )
            )

            # Mock get_core_pr_integrations - returns list of integration domains
            mock_api.get_core_pr_integrations = AsyncMock(
                return_value=["niko_home_control"]
            )

            # Mock manifest content for core integration
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "niko_home_control", "name": "Niko Home Control"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            with patch(
                "custom_components.integration_tester.helpers.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {
                        "url": "https://github.com/home-assistant/core/pull/134000",
                        "github_token": "test_token",
                    },
                )

        # Should create entry directly since only one integration is modified
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_INTEGRATION_DOMAIN] == "niko_home_control"

    @pytest.mark.asyncio
    async def test_form_github_error(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow with GitHub API error."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference to raise error
            mock_api.resolve_reference = AsyncMock(
                side_effect=GitHubAPIError("API Error")
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "url": "https://github.com/owner/repo/pull/1",
                    "github_token": "test_token",
                },
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "github_error"}

    @pytest.mark.asyncio
    async def test_form_already_configured_same_repo(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow when integration is already configured from same repo."""
        # Create existing entry with same repo URL
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_INTEGRATION_DOMAIN: "lock_code_manager",
                CONF_URL: "https://github.com/raman325/lock_code_manager",
            },
            unique_id="lock_code_manager",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )

            # Mock HACS validation
            mock_api.file_exists = AsyncMock(return_value=True)
            mock_api.get_directory_contents = AsyncMock(
                return_value=[{"name": "lock_code_manager", "type": "dir"}]
            )
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "lock_code_manager", "name": "Lock Code Manager"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "url": "https://github.com/raman325/lock_code_manager/pull/1",
                    "github_token": "test_token",
                },
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured_same_repo"

    @pytest.mark.asyncio
    async def test_form_already_configured_different_repo(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow when integration is already configured from different repo."""
        # Create existing entry with different repo URL
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_INTEGRATION_DOMAIN: "lock_code_manager",
                CONF_URL: "https://github.com/other_owner/lock_code_manager",
            },
            unique_id="lock_code_manager",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )

            # Mock HACS validation
            mock_api.file_exists = AsyncMock(return_value=True)
            mock_api.get_directory_contents = AsyncMock(
                return_value=[{"name": "lock_code_manager", "type": "dir"}]
            )
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "lock_code_manager", "name": "Lock Code Manager"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "url": "https://github.com/raman325/lock_code_manager/pull/1",
                    "github_token": "test_token",
                },
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured_different_repo"

    @pytest.mark.asyncio
    async def test_form_confirm_overwrite(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow with existing integration prompts for overwrite."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )

            # Mock HACS validation
            mock_api.file_exists = AsyncMock(return_value=True)
            mock_api.get_directory_contents = AsyncMock(
                return_value=[{"name": "lock_code_manager", "type": "dir"}]
            )
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "lock_code_manager", "name": "Lock Code Manager"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            with (
                patch(
                    "custom_components.integration_tester.config_flow.integration_exists",
                    return_value=True,
                ),
                patch(
                    "custom_components.integration_tester.config_flow.integration_has_marker",
                    return_value=False,
                ),
            ):
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {
                        "url": "https://github.com/raman325/lock_code_manager/pull/1",
                        "github_token": "test_token",
                    },
                )

        # Should show confirmation form
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "confirm_overwrite"

    @pytest.mark.asyncio
    async def test_form_core_pr_multiple_integrations(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow with core PR that modifies multiple integrations."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference to return ResolvedReference for core repo
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference(
                    owner="home-assistant",
                    repo="core",
                    reference_type=ReferenceType.PR,
                    reference_value="134000",
                    is_part_of_ha_core=True,
                    commit_sha="63bc46580b3dcd930c1bf6839ba6ca2cc82d900f",
                )
            )

            # Mock get_core_pr_integrations - returns multiple integrations
            mock_api.get_core_pr_integrations = AsyncMock(
                return_value=["hue", "zwave_js", "mqtt"]
            )

            # Mock manifest content for core integration
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "hue", "name": "Philips Hue"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "url": "https://github.com/home-assistant/core/pull/134000",
                    "github_token": "test_token",
                },
            )

        # Should show integration selection form
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_integration"

    @pytest.mark.asyncio
    async def test_form_select_integration_step(
        self,
        hass: HomeAssistant,
    ):
        """Test selecting integration from multiple options."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            # Mock token validation
            mock_api.validate_token = AsyncMock(return_value=True)

            # Mock resolve_reference for core repo
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference(
                    owner="home-assistant",
                    repo="core",
                    reference_type=ReferenceType.PR,
                    reference_value="134000",
                    is_part_of_ha_core=True,
                    commit_sha="63bc46580b3dcd930c1bf6839ba6ca2cc82d900f",
                )
            )

            # Mock get_core_pr_integrations - returns multiple integrations
            mock_api.get_core_pr_integrations = AsyncMock(
                return_value=["hue", "zwave_js"]
            )

            # Mock manifest content
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "hue", "name": "Philips Hue"}'
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "url": "https://github.com/home-assistant/core/pull/134000",
                    "github_token": "test_token",
                },
            )

            # Now select an integration
            with patch(
                "custom_components.integration_tester.config_flow.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {"domain": "hue"},
                )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_INTEGRATION_DOMAIN] == "hue"


class TestOptionsFlow:
    """Tests for options flow."""

    @pytest.mark.asyncio
    async def test_options_flow_update_token(self, hass: HomeAssistant):
        """Test updating token via options flow."""
        # Create existing entry
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_INTEGRATION_DOMAIN: "test_domain",
                CONF_URL: "https://github.com/owner/repo",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
            },
            unique_id="test_domain",
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            mock_api.validate_token = AsyncMock(return_value=True)

            # Initialize options flow
            result = await hass.config_entries.options.async_init(entry.entry_id)

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "init"

            # Submit new token
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {CONF_GITHUB_TOKEN: "new_test_token"},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        # Token should be stored in hass.data
        assert hass.data[DOMAIN][CONF_GITHUB_TOKEN] == "new_test_token"
