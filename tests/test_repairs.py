"""Tests for repair issue handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant

from custom_components.integration_tester.const import (
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    REPAIR_RESTART_REQUIRED,
    REPAIR_TOKEN_INVALID,
    ReferenceType,
)
from custom_components.integration_tester.repairs import (
    DeleteConfigEntryRepairFlow,
    RestartRequiredRepairFlow,
    async_create_fix_flow,
    create_download_failed_issue,
    create_integration_removed_issue,
    create_pr_closed_issue,
    create_restart_required_issue,
    create_token_invalid_issue,
    is_repair_issue_acknowledged,
    remove_download_failed_issue,
    remove_integration_removed_issue,
    remove_pr_closed_issue,
    remove_restart_required_issue,
    remove_token_invalid_issue,
)

from .conftest import create_config_entry


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
        },
        unique_id="test_domain",
    )
    entry.add_to_hass(hass)
    return entry


class TestRepairIssueCreation:
    """Tests for repair issue creation functions."""

    def test_create_restart_required_issue(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test creating restart required issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_restart_required_issue(hass, mock_config_entry, "test_domain")

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "restart_required"
        assert call_kwargs["translation_placeholders"]["domain"] == "test_domain"

    def test_remove_restart_required_issue(self, hass: HomeAssistant):
        """Test removing restart required issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_delete_issue"
        ) as mock_delete:
            remove_restart_required_issue(hass, "test_domain")

        mock_delete.assert_called_once_with(
            hass, DOMAIN, REPAIR_RESTART_REQUIRED.format(domain="test_domain")
        )

    def test_create_pr_closed_issue_merged(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test creating PR merged issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_pr_closed_issue(
                hass, mock_config_entry, "test_domain", pr_number=123, is_merged=True
            )

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "pr_merged"

    def test_create_pr_closed_issue_not_merged(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test creating PR closed (not merged) issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_pr_closed_issue(
                hass, mock_config_entry, "test_domain", pr_number=123, is_merged=False
            )

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "pr_closed"

    def test_remove_pr_closed_issue(self, hass: HomeAssistant):
        """Test removing PR closed issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_delete_issue"
        ) as mock_delete:
            remove_pr_closed_issue(hass, "test_domain")

        mock_delete.assert_called_once()

    def test_create_integration_removed_issue(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test creating integration removed issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_integration_removed_issue(hass, mock_config_entry, "test_domain")

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "integration_removed"

    def test_remove_integration_removed_issue(self, hass: HomeAssistant):
        """Test removing integration removed issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_delete_issue"
        ) as mock_delete:
            remove_integration_removed_issue(hass, "test_domain")

        mock_delete.assert_called_once()

    def test_create_download_failed_issue(self, hass: HomeAssistant, mock_config_entry):
        """Test creating download failed issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_download_failed_issue(
                hass, mock_config_entry, "test_domain", "Connection error"
            )

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "download_failed"
        assert call_kwargs["translation_placeholders"]["error"] == "Connection error"

    def test_remove_download_failed_issue(self, hass: HomeAssistant):
        """Test removing download failed issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_delete_issue"
        ) as mock_delete:
            remove_download_failed_issue(hass, "test_domain")

        mock_delete.assert_called_once()

    def test_create_token_invalid_issue(self, hass: HomeAssistant):
        """Test creating token invalid issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_create_issue"
        ) as mock_create:
            create_token_invalid_issue(hass)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["translation_key"] == "token_invalid"

    def test_remove_token_invalid_issue(self, hass: HomeAssistant):
        """Test removing token invalid issue."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_delete_issue"
        ) as mock_delete:
            remove_token_invalid_issue(hass)

        mock_delete.assert_called_once_with(hass, DOMAIN, REPAIR_TOKEN_INVALID)


class TestIsRepairIssueAcknowledged:
    """Tests for is_repair_issue_acknowledged."""

    def test_issue_exists(self, hass: HomeAssistant):
        """Test when issue exists (not acknowledged)."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_get"
        ) as mock_get:
            mock_registry = MagicMock()
            mock_registry.async_get_issue.return_value = MagicMock()  # Issue exists
            mock_get.return_value = mock_registry

            result = is_repair_issue_acknowledged(hass, "test_issue")

        assert result is False

    def test_issue_not_exists(self, hass: HomeAssistant):
        """Test when issue doesn't exist (acknowledged/dismissed)."""
        with patch(
            "custom_components.integration_tester.repairs.ir.async_get"
        ) as mock_get:
            mock_registry = MagicMock()
            mock_registry.async_get_issue.return_value = None  # Issue doesn't exist
            mock_get.return_value = mock_registry

            result = is_repair_issue_acknowledged(hass, "test_issue")

        assert result is True


class TestAsyncCreateFixFlow:
    """Tests for async_create_fix_flow."""

    @pytest.mark.asyncio
    async def test_restart_required_flow(self, hass: HomeAssistant):
        """Test creating restart required flow."""
        flow = await async_create_fix_flow(hass, "restart_required_test", None)
        assert isinstance(flow, RestartRequiredRepairFlow)

    @pytest.mark.asyncio
    async def test_pr_closed_flow(self, hass: HomeAssistant):
        """Test creating PR closed flow."""
        flow = await async_create_fix_flow(
            hass, "pr_closed_test", {"entry_id": "test_entry"}
        )
        assert isinstance(flow, DeleteConfigEntryRepairFlow)

    @pytest.mark.asyncio
    async def test_integration_removed_flow(self, hass: HomeAssistant):
        """Test creating integration removed flow."""
        flow = await async_create_fix_flow(
            hass, "integration_removed_test", {"entry_id": "test_entry"}
        )
        assert isinstance(flow, DeleteConfigEntryRepairFlow)

    @pytest.mark.asyncio
    async def test_default_flow(self, hass: HomeAssistant):
        """Test default confirm flow for unknown issues."""
        flow = await async_create_fix_flow(hass, "unknown_issue", None)
        assert isinstance(flow, ConfirmRepairFlow)


class TestRestartRequiredRepairFlow:
    """Tests for RestartRequiredRepairFlow."""

    @pytest.mark.asyncio
    async def test_async_step_init_no_input(self, hass: HomeAssistant):
        """Test flow shows form when no input."""
        flow = RestartRequiredRepairFlow()
        flow.hass = hass

        result = await flow.async_step_init(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_async_step_init_with_input(self, hass: HomeAssistant):
        """Test flow triggers restart when user confirms."""
        flow = RestartRequiredRepairFlow()
        # Create a mock hass with mocked services
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        flow.hass = mock_hass

        result = await flow.async_step_init(user_input={})

        assert result["type"] == "create_entry"
        mock_hass.services.async_call.assert_called_once_with(
            "homeassistant", "restart"
        )


class TestDeleteConfigEntryRepairFlow:
    """Tests for DeleteConfigEntryRepairFlow."""

    @pytest.mark.asyncio
    async def test_async_step_init_no_input(self, hass: HomeAssistant):
        """Test flow shows form when no input."""
        flow = DeleteConfigEntryRepairFlow(entry_id="test_entry_id")
        flow.hass = hass

        result = await flow.async_step_init(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_async_step_init_with_input_entry_exists(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test flow deletes config entry when user confirms."""
        flow = DeleteConfigEntryRepairFlow(entry_id=mock_config_entry.entry_id)
        flow.hass = hass

        with patch.object(
            hass.config_entries, "async_remove", new_callable=AsyncMock
        ) as mock_remove:
            result = await flow.async_step_init(user_input={})

        assert result["type"] == "create_entry"
        mock_remove.assert_called_once_with(mock_config_entry.entry_id)

    @pytest.mark.asyncio
    async def test_async_step_init_with_input_entry_not_found(
        self, hass: HomeAssistant
    ):
        """Test flow handles missing config entry gracefully."""
        flow = DeleteConfigEntryRepairFlow(entry_id="nonexistent_entry")
        flow.hass = hass

        # Should not raise even if entry doesn't exist
        result = await flow.async_step_init(user_input={})

        assert result["type"] == "create_entry"
