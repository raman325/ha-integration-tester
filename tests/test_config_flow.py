"""Tests for config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

    async def test_form_with_restart_option(self, hass: HomeAssistant):
        """Test user flow with restart=True stores option in entry."""
        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            mock_api.validate_token = AsyncMock(return_value=True)
            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )
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

            with patch(
                "custom_components.integration_tester.helpers.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {
                        "url": "https://github.com/raman325/lock_code_manager/pull/1",
                        "github_token": "test_token",
                        "restart": True,
                    },
                )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        # Verify restart option is stored in entry options
        assert result["options"].get("restart_after_install") is True

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

    async def test_form_already_configured_shows_confirm_step(
        self,
        hass: HomeAssistant,
    ):
        """Test config flow when integration is already configured shows confirm step."""
        # Create existing entry
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

        # Now shows confirm step instead of aborting
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "confirm_entry_overwrite"

    async def test_form_already_configured_confirm_overwrites(
        self,
        hass: HomeAssistant,
    ):
        """Test confirming overwrite removes existing entry and creates new one."""
        # Create existing entry
        existing_entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Test",
            data={
                CONF_INTEGRATION_DOMAIN: "lock_code_manager",
                CONF_URL: "https://github.com/other_owner/lock_code_manager",
            },
            unique_id="lock_code_manager",
        )
        existing_entry.add_to_hass(hass)

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

            # Should show confirm step
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "confirm_entry_overwrite"

            # Confirm overwrite
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"confirm": True},
            )

        # Should create new entry (old one was removed)
        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_form_already_configured_cancel_aborts(
        self,
        hass: HomeAssistant,
    ):
        """Test cancelling overwrite aborts the flow."""
        # Create existing entry
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

            # Should show confirm step
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "confirm_entry_overwrite"

            # Cancel overwrite
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"confirm": False},
            )

        # Should abort
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "user_cancelled"

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


class TestImportFlow:
    """Tests for import flow (service-triggered)."""

    async def test_import_success(self, hass: HomeAssistant):
        """Test successful import flow."""
        # Set up token in hass.data
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

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

            with patch(
                "custom_components.integration_tester.helpers.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data={
                        "url": "https://github.com/raman325/lock_code_manager/pull/1"
                    },
                )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "Lock Code Manager" in result["title"]

    async def test_import_missing_url(self, hass: HomeAssistant):
        """Test import flow aborts when URL is missing."""
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data={},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "missing_url"

    async def test_import_invalid_url(self, hass: HomeAssistant):
        """Test import flow aborts for invalid URL."""
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data={"url": "not-a-valid-url"},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "invalid_url"

    async def test_import_no_token(self, hass: HomeAssistant):
        """Test import flow aborts when no token configured."""
        # No token in hass.data
        hass.data[DOMAIN] = {}

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data={"url": "https://github.com/owner/repo/pull/1"},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_token"

    async def test_import_github_error(self, hass: HomeAssistant):
        """Test import flow aborts on GitHub API error."""
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            mock_api.resolve_reference = AsyncMock(
                side_effect=GitHubAPIError("API Error")
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={"url": "https://github.com/owner/repo/pull/1"},
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "github_error"

    async def test_import_core_pr_multiple_integrations(self, hass: HomeAssistant):
        """Test import flow aborts for core PR with multiple integrations."""
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference(
                    owner="home-assistant",
                    repo="core",
                    reference_type=ReferenceType.PR,
                    reference_value="134000",
                    is_part_of_ha_core=True,
                )
            )

            # Multiple integrations modified
            mock_api.get_core_pr_integrations = AsyncMock(
                return_value=["hue", "zwave_js"]
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={"url": "https://github.com/home-assistant/core/pull/134000"},
            )

        # Should abort - multi-integration core PRs require UI selection
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "multiple_integrations_found"

    async def test_import_with_overwrite_existing_entry(self, hass: HomeAssistant):
        """Test import with overwrite=True removes existing entry."""
        hass.data[DOMAIN] = {CONF_GITHUB_TOKEN: "test_token"}

        # Create existing entry for same domain
        existing_entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Existing Entry",
            data={
                CONF_URL: "https://github.com/old_owner/old_repo/pull/1",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "lock_code_manager",
            },
            unique_id="lock_code_manager",
        )
        existing_entry.add_to_hass(hass)

        with patch(
            "custom_components.integration_tester.config_flow.IntegrationTesterGitHubAPI"
        ) as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api

            mock_api.resolve_reference = AsyncMock(
                return_value=create_resolved_reference()
            )
            mock_api.file_exists = AsyncMock(return_value=True)
            mock_api.get_directory_contents = AsyncMock(
                return_value=[{"name": "lock_code_manager", "type": "dir"}]
            )
            mock_api.get_file_content = AsyncMock(
                return_value='{"domain": "lock_code_manager", "name": "Lock Code Manager"}'
            )

            with patch(
                "custom_components.integration_tester.helpers.integration_exists",
                return_value=False,
            ):
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data={
                        "url": "https://github.com/raman325/lock_code_manager/pull/1",
                        "overwrite": True,
                    },
                )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        # Verify new entry was created with new URL
        assert "Lock Code Manager" in result["title"]


class TestOptionsFlow:
    """Tests for options flow."""

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
