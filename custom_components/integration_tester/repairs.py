"""Repair issue handlers for Integration Tester."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    REPAIR_DOWNLOAD_FAILED,
    REPAIR_INTEGRATION_REMOVED,
    REPAIR_PR_CLOSED,
    REPAIR_RESTART_REQUIRED,
    REPAIR_TOKEN_INVALID,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class RestartRequiredRepairFlow(ConfirmRepairFlow):
    """Handler for restart required repair flow."""

    async def async_step_init(self, user_input: dict | None = None) -> dict:
        """Handle the first step of the repair flow."""
        if user_input is not None:
            # User confirmed, restart Home Assistant
            await self.hass.services.async_call("homeassistant", "restart")
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="init")


class DeleteConfigEntryRepairFlow(RepairsFlow):
    """Handler for repair flows that delete the config entry."""

    def __init__(self, entry_id: str) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict | None = None) -> dict:
        """Handle the first step of the repair flow."""
        if user_input is not None:
            # Delete the config entry
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry:
                await self.hass.config_entries.async_remove(self._entry_id)
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="init")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict | None,
) -> RepairsFlow:
    """Create flow for fixing an issue."""
    if issue_id.startswith("restart_required_"):
        return RestartRequiredRepairFlow()

    if issue_id.startswith("pr_closed_") or issue_id.startswith("integration_removed_"):
        entry_id = data.get("entry_id") if data else None
        if entry_id:
            return DeleteConfigEntryRepairFlow(entry_id)

    # Default: just confirm to dismiss
    return ConfirmRepairFlow()


@callback
def create_restart_required_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
) -> None:
    """Create a repair issue indicating restart is required."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_RESTART_REQUIRED.format(domain=domain),
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="restart_required",
        translation_placeholders={"domain": domain},
        data={"entry_id": entry.entry_id},
    )


@callback
def remove_restart_required_issue(
    hass: HomeAssistant,
    domain: str,
) -> None:
    """Remove the restart required repair issue."""
    ir.async_delete_issue(hass, DOMAIN, REPAIR_RESTART_REQUIRED.format(domain=domain))


@callback
def create_pr_closed_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
    pr_number: int,
    is_merged: bool,
) -> None:
    """Create a repair issue indicating PR was closed/merged."""
    translation_key = "pr_merged" if is_merged else "pr_closed"
    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_PR_CLOSED.format(domain=domain),
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=translation_key,
        translation_placeholders={
            "domain": domain,
            "pr_number": str(pr_number),
        },
        data={"entry_id": entry.entry_id},
    )


@callback
def remove_pr_closed_issue(
    hass: HomeAssistant,
    domain: str,
) -> None:
    """Remove the PR closed repair issue."""
    ir.async_delete_issue(hass, DOMAIN, REPAIR_PR_CLOSED.format(domain=domain))


@callback
def create_integration_removed_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
) -> None:
    """Create a repair issue indicating integration was removed from diff."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_INTEGRATION_REMOVED.format(domain=domain),
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="integration_removed",
        translation_placeholders={"domain": domain},
        data={"entry_id": entry.entry_id},
    )


@callback
def remove_integration_removed_issue(
    hass: HomeAssistant,
    domain: str,
) -> None:
    """Remove the integration removed repair issue."""
    ir.async_delete_issue(
        hass, DOMAIN, REPAIR_INTEGRATION_REMOVED.format(domain=domain)
    )


@callback
def create_download_failed_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
    error_message: str,
) -> None:
    """Create a repair issue indicating download failed."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_DOWNLOAD_FAILED.format(domain=domain),
        is_fixable=False,  # No fix action - auto-resolves when successful
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="download_failed",
        translation_placeholders={
            "domain": domain,
            "error": error_message,
        },
        data={"entry_id": entry.entry_id},
    )


@callback
def remove_download_failed_issue(
    hass: HomeAssistant,
    domain: str,
) -> None:
    """Remove the download failed repair issue."""
    ir.async_delete_issue(hass, DOMAIN, REPAIR_DOWNLOAD_FAILED.format(domain=domain))


def is_repair_issue_acknowledged(
    hass: HomeAssistant,
    issue_id: str,
) -> bool:
    """Check if a repair issue has been acknowledged (dismissed)."""
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    return issue is None


@callback
def create_token_invalid_issue(hass: HomeAssistant) -> None:
    """
    Create a repair issue indicating the GitHub token is invalid.

    This is a global issue (not per-domain) since the token is shared.

    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_TOKEN_INVALID,
        is_fixable=False,  # User needs to update token via options flow
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="token_invalid",
    )


@callback
def remove_token_invalid_issue(hass: HomeAssistant) -> None:
    """Remove the token invalid repair issue."""
    ir.async_delete_issue(hass, DOMAIN, REPAIR_TOKEN_INVALID)
