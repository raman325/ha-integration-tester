"""Config flow for Integration Tester."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IntegrationTesterGitHubAPI
from .const import (
    CONF_GITHUB_TOKEN,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_PART_OF_HA_CORE,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
)
from .exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    InvalidGitHubURLError,
    ManifestNotFoundError,
)
from .helpers import (
    get_core_integration_info,
    integration_exists,
    integration_has_marker,
    parse_github_url,
    validate_custom_integration,
)
from .models import IntegrationInfo, ResolvedReference
from .storage import async_save_token

_LOGGER = logging.getLogger(__name__)


class IntegrationTesterConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for Integration Tester.

    The flow differs for core vs external repositories:

    External repos (HACS-style custom integrations):
      1. Validate repo structure has custom_components/<domain>/manifest.json
      2. Extract domain and integration info from manifest
      3. Check for conflicts, create entry

    Core repos (home-assistant/core or forks):
      1. Get list of integrations modified in the PR diff
      2. User selects integration (or auto-select if only one)
      3. Check for conflicts, create entry
      4. Fetch integration info from manifest at entry creation time

    The key difference: external repos need early validation (structure might not
    exist), while core repos skip validation (we know the integration exists from
    the PR diff). Integration info is fetched at different times accordingly.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api: IntegrationTesterGitHubAPI | None = None
        self._resolved: ResolvedReference | None = None
        # Integration info is set early for external repos, late for core repos
        self._integration_info: IntegrationInfo | None = None
        # For core PRs that modify multiple integrations
        self._available_integrations: list[str] = []
        self._selected_domain: str | None = None
        self._restart_after_install: bool = False
        self._overwrite_existing: bool = False
        self._existing_entry_to_remove: ConfigEntry | None = None

    def _get_user_schema(self) -> vol.Schema:
        """Get the schema for the user step, including token field if not configured."""
        schema: dict[vol.Marker, Any] = {vol.Required("url"): cv.string}

        # Require token if not already configured
        if not self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN):
            schema[vol.Required(CONF_GITHUB_TOKEN)] = cv.string

        # Add restart option
        schema[vol.Optional("restart", default=False)] = cv.boolean

        return vol.Schema(schema)

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle import from service call."""
        # Import step receives {"url": "...", "overwrite": bool, "restart": bool}
        # Process like user step but without showing forms on error
        url = import_data.get("url")
        if not url:
            return self.async_abort(reason="missing_url")

        # Store options from import data
        self._overwrite_existing = import_data.get("overwrite", False)
        self._restart_after_install = import_data.get("restart", False)

        try:
            parsed_url = parse_github_url(url)
        except InvalidGitHubURLError:
            return self.async_abort(reason="invalid_url")

        # Check if token is configured
        token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN)
        if not token:
            return self.async_abort(reason="no_token")

        session = async_get_clientsession(self.hass)
        self._api = IntegrationTesterGitHubAPI(session, token)

        try:
            self._resolved = await self._api.resolve_reference(parsed_url)

            if self._resolved.is_part_of_ha_core:
                # For core PRs, we need user interaction to select integration
                if self._resolved.reference_type == ReferenceType.PR:
                    integrations = await self._api.get_core_pr_integrations(
                        self._resolved.owner,
                        self._resolved.repo,
                        int(self._resolved.reference_value),
                    )
                    if not integrations:
                        return self.async_abort(reason="no_integrations_found")
                    if len(integrations) > 1:
                        # Multiple integrations - can't complete via import/service
                        return self.async_abort(reason="multiple_integrations_found")
                    self._selected_domain = integrations[0]
                else:
                    return self.async_abort(reason="import_core_requires_pr")
            else:
                # External repo
                self._integration_info = await validate_custom_integration(
                    self._api,
                    self._resolved.owner,
                    self._resolved.repo,
                    self._resolved.commit_sha,
                )
                self._selected_domain = self._integration_info.domain

            return await self._check_existing_integration()

        except ManifestNotFoundError:
            return self.async_abort(reason="manifest_not_found")
        except GitHubAPIError as err:
            _LOGGER.error("GitHub API error during import: %s", err)
            return self.async_abort(
                reason="github_error", description_placeholders={"error": str(err)}
            )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            # Store restart preference
            self._restart_after_install = user_input.get("restart", False)

            session = async_get_clientsession(self.hass)

            # Only validate token if it was provided in the form (not already stored)
            if CONF_GITHUB_TOKEN in user_input:
                token = user_input[CONF_GITHUB_TOKEN]
                try:
                    test_api = IntegrationTesterGitHubAPI(session, token)
                    if not await test_api.validate_token():
                        errors[CONF_GITHUB_TOKEN] = "invalid_token"
                except GitHubAuthError:
                    errors[CONF_GITHUB_TOKEN] = "invalid_token"
                except GitHubAPIError as err:
                    _LOGGER.error("GitHub API error validating token: %s", err)
                    errors["base"] = "github_error"
                    description_placeholders["error"] = str(err)
                else:
                    # Token is valid, store it in memory and persist to storage
                    self.hass.data.setdefault(DOMAIN, {})[CONF_GITHUB_TOKEN] = token
                    await async_save_token(self.hass, token)

                if errors:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._get_user_schema(),
                        errors=errors,
                        description_placeholders=description_placeholders,
                    )

            try:
                parsed_url = parse_github_url(user_input["url"])
            except InvalidGitHubURLError:
                errors["url"] = "invalid_url"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(),
                    errors=errors,
                )

            # Initialize API client with validated token
            token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN)
            self._api = IntegrationTesterGitHubAPI(session, token)

            try:
                # Resolve the reference to get commit SHA and all context
                self._resolved = await self._api.resolve_reference(parsed_url)

                # Core and external repos have different flows (see class docstring)
                if self._resolved.is_part_of_ha_core:
                    return await self._select_core_integration()
                return await self._validate_external_integration()

            except GitHubAPIError as err:
                _LOGGER.error("GitHub API error: %s", err)
                errors["base"] = "github_error"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(),
                    errors=errors,
                    description_placeholders={"error": str(err)},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_user_schema(),
            errors=errors,
        )

    async def _select_core_integration(self) -> ConfigFlowResult:
        """
        Identify and select integration from a core repository PR.

        For core repos, we determine which integration to install by examining
        which files are modified in the PR. No validation is needed since we
        know the integration exists in the core codebase.

        Sets _selected_domain directly if only one integration is modified,
        otherwise prompts user to select from available integrations.
        """
        # Get integrations modified in this PR
        if self._resolved.reference_type == ReferenceType.PR:
            self._available_integrations = await self._api.get_core_pr_integrations(
                self._resolved.owner,
                self._resolved.repo,
                int(self._resolved.reference_value),
            )
        else:
            # For branches/commits, we can't easily determine which integrations
            # are modified without comparing to base. For now, require PR URL
            # for core repo or let user specify the integration.
            return self.async_show_form(
                step_id="user",
                data_schema=self._get_user_schema(),
                errors={"url": "core_requires_pr"},
            )

        if not self._available_integrations:
            return self.async_show_form(
                step_id="user",
                data_schema=self._get_user_schema(),
                errors={"url": "no_integrations_found"},
            )

        if len(self._available_integrations) == 1:
            # Only one integration, select it automatically
            self._selected_domain = self._available_integrations[0]
            return await self._check_existing_integration()

        # Multiple integrations, let user select
        return await self.async_step_select_integration()

    async def _validate_external_integration(self) -> ConfigFlowResult:
        """
        Validate and extract info from an external (HACS-style) repository.

        External repos must have the structure custom_components/<domain>/manifest.json.
        We validate this early because the structure might not exist, unlike core repos
        where we already know the integration exists from the PR diff.

        Sets both _selected_domain and _integration_info since we're reading the
        manifest anyway.
        """
        try:
            # Validates structure exists AND extracts integration info
            self._integration_info = await validate_custom_integration(
                self._api,
                self._resolved.owner,
                self._resolved.repo,
                self._resolved.commit_sha,
            )
            self._selected_domain = self._integration_info.domain
            return await self._check_existing_integration()
        except ManifestNotFoundError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._get_user_schema(),
                errors={"url": "manifest_not_found"},
            )

    async def async_step_select_integration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle integration selection for core PRs with multiple integrations."""
        if user_input is not None:
            self._selected_domain = user_input["domain"]
            return await self._check_existing_integration()

        schema = vol.Schema(
            {
                vol.Required("domain"): vol.In(self._available_integrations),
            }
        )

        return self.async_show_form(
            step_id="select_integration",
            data_schema=schema,
            description_placeholders={
                "integrations": ", ".join(self._available_integrations)
            },
        )

    async def _check_existing_integration(self) -> ConfigFlowResult:
        """
        Check for conflicts with existing integrations.

        Handles three cases:
        1. Already tracked by Integration Tester → confirm overwrite (auto-remove if overwrite=True)
        2. Folder exists with our marker (switching reference) → proceed
        3. Folder exists but not managed by us → confirm overwrite
        """
        await self.async_set_unique_id(self._selected_domain)

        # Check for existing Integration Tester entry with same unique ID
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == self.unique_id:
                # If overwrite was requested (from service), remove existing and proceed
                if self._overwrite_existing:
                    self._existing_entry_to_remove = entry
                    return await self._remove_existing_and_create()
                # Otherwise, show confirmation step (for UI flow)
                self._existing_entry_to_remove = entry
                return await self.async_step_confirm_entry_overwrite()

        # Check if folder exists
        if integration_exists(self.hass, self._selected_domain):
            if integration_has_marker(self.hass, self._selected_domain):
                # We manage it, can proceed (switching reference)
                return await self._create_entry()
            else:
                # Not managed by us, show confirmation
                return await self.async_step_confirm_overwrite()

        return await self._create_entry()

    async def async_step_confirm_overwrite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle confirmation to overwrite existing integration files (not managed by us)."""
        if user_input is not None:
            if user_input.get("confirm"):
                return await self._create_entry()
            else:
                return self.async_abort(reason="user_cancelled")

        return self.async_show_form(
            step_id="confirm_overwrite",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
            description_placeholders={"domain": self._selected_domain},
        )

    async def async_step_confirm_entry_overwrite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle confirmation to overwrite existing Integration Tester entry."""
        if user_input is not None:
            if user_input.get("confirm"):
                self._overwrite_existing = True
                return await self._remove_existing_and_create()
            else:
                return self.async_abort(reason="user_cancelled")

        # Get info about existing entry for display
        existing_url = ""
        if self._existing_entry_to_remove:
            existing_url = self._existing_entry_to_remove.data.get(CONF_URL, "")

        return self.async_show_form(
            step_id="confirm_entry_overwrite",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
            description_placeholders={
                "domain": self._selected_domain,
                "existing_url": existing_url,
            },
        )

    async def _remove_existing_and_create(self) -> ConfigFlowResult:
        """Remove existing entry and create new one."""
        if self._existing_entry_to_remove:
            await self.hass.config_entries.async_remove(
                self._existing_entry_to_remove.entry_id
            )
            self._existing_entry_to_remove = None
        return await self._create_entry()

    async def _create_entry(self) -> ConfigFlowResult:
        """
        Create the config entry.

        For core repos, this is where we fetch the integration info (name from
        manifest). We defer this until entry creation because:
        1. We don't need it for validation (unlike external repos)
        2. For multi-integration PRs, we don't know the domain until user selects

        For external repos, _integration_info is already set from validation.
        """
        # Fetch integration info for core repos (external repos already have it)
        if self._integration_info is None and self._resolved.is_part_of_ha_core:
            ref = self._get_current_ref()
            self._integration_info = await get_core_integration_info(
                self._api,
                self._resolved.owner,
                self._resolved.repo,
                self._selected_domain,
                ref,
            )

        # Determine title
        ref_type = self._resolved.reference_type
        if ref_type == ReferenceType.PR:
            ref_str = f"PR #{self._resolved.reference_value}"
        elif ref_type == ReferenceType.BRANCH:
            ref_str = f"branch: {self._resolved.reference_value}"
        else:
            ref_str = f"commit: {self._resolved.reference_value[:7]}"

        name = (
            self._integration_info.name
            if self._integration_info
            else self._selected_domain
        )
        title = f"{name} ({ref_str})"

        # Build minimal data (dynamic fields derived by coordinator)
        # Store normalized URL (just owner/repo) since reference_type/value are separate
        # Note: CONF_INSTALLED_COMMIT is intentionally NOT set here - it's set by
        # async_setup_entry after successful download to trigger the install flow.
        data = {
            CONF_URL: self._resolved.repo_url,
            CONF_REFERENCE_TYPE: self._resolved.reference_type.value,
            CONF_REFERENCE_VALUE: self._resolved.reference_value,
            CONF_INTEGRATION_DOMAIN: self._selected_domain,
            CONF_IS_PART_OF_HA_CORE: self._resolved.is_part_of_ha_core,
        }

        # Store restart flag in entry options (avoids race condition with domain-keyed state)
        options = {}
        if self._restart_after_install:
            options["restart_after_install"] = True

        return self.async_create_entry(title=title, data=data, options=options)

    def _get_current_ref(self) -> str:
        """Get the current commit SHA."""
        if self._resolved:
            return self._resolved.commit_sha
        return ""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return IntegrationTesterOptionsFlow(config_entry)


class IntegrationTesterOptionsFlow(OptionsFlow):
    """Handle options flow for Integration Tester."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {
            "domain": self._config_entry.data.get(CONF_INTEGRATION_DOMAIN, "")
        }

        # Default to current stored token for initial form display
        token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN, "")

        if user_input is not None:
            # If we display form after it has been filled, it's due to an error and we
            # want to preserve the entered token value
            token = user_input[CONF_GITHUB_TOKEN]

            # Validate the new token
            session = async_get_clientsession(self.hass)
            api = IntegrationTesterGitHubAPI(session, token)
            try:
                valid_token = await api.validate_token()
            except GitHubAuthError:
                errors[CONF_GITHUB_TOKEN] = "invalid_token"
            except GitHubAPIError as err:
                _LOGGER.error("GitHub API error validating token: %s", err)
                errors["base"] = "github_error"
                description_placeholders["error"] = str(err)
            else:
                if not valid_token:
                    errors[CONF_GITHUB_TOKEN] = "invalid_token"
                else:
                    # Token is valid, store it in memory and persist to storage
                    self.hass.data.setdefault(DOMAIN, {})[CONF_GITHUB_TOKEN] = token
                    await async_save_token(self.hass, token)
                    return self.async_create_entry(title="", data={})

        desc = {"suggested_value": token} if token else vol.UNDEFINED
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_GITHUB_TOKEN, description=desc): cv.string}
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
