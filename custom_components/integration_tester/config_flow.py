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
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import IntegrationTesterGitHubAPI
from .const import (
    CONF_CUSTOM_REFERENCE,
    CONF_GITHUB_TOKEN,
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_PART_OF_HA_CORE,
    CONF_REFERENCE_CHOICE,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    REFERENCE_NOT_LISTED,
    ReferenceType,
)
from .exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    IntegrationNotFoundError,
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
from .models import IntegrationInfo, ParsedGitHubURL, ReferenceOption, ResolvedReference
from .repairs import (
    remove_download_failed_issue,
    remove_integration_removed_issue,
    remove_pr_closed_issue,
)
from .storage import async_save_token

_LOGGER = logging.getLogger(__name__)

REFERENCE_TYPE_NAMES: dict[ReferenceType, str] = {
    ReferenceType.BRANCH: "branch",
    ReferenceType.PR: "pull request",
    ReferenceType.COMMIT: "commit",
}


def _build_title(name: str, ref_type: ReferenceType, ref_value: str) -> str:
    """Build a config entry title from the integration name and reference."""
    if ref_type == ReferenceType.PR:
        ref_str = f"PR #{ref_value}"
    elif ref_type == ReferenceType.BRANCH:
        ref_str = f"branch: {ref_value}"
    else:
        ref_str = f"commit: {ref_value[:7]}"
    return f"{name} ({ref_str})"


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
        # Reconfigure flow state
        self._reconfigure_type: ReferenceType = ReferenceType.BRANCH
        self._reference_options: list[ReferenceOption] | None = None

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
        """
        Handle import from service call.

        Receives: {"url": "...", "overwrite": bool, "restart": bool, "domain": str|None}
        """
        url = import_data.get("url")
        if not url:
            return self.async_abort(reason="missing_url")

        # Store options from import data
        self._overwrite_existing = import_data.get("overwrite", False)
        self._restart_after_install = import_data.get("restart", False)
        requested_domain = import_data.get("domain")

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
                if self._resolved.reference_type == ReferenceType.PR:
                    integrations = await self._api.get_core_pr_integrations(
                        self._resolved.owner,
                        self._resolved.repo,
                        int(self._resolved.reference_value),
                    )
                    if not integrations:
                        return self.async_abort(reason="no_integrations_found")
                    if len(integrations) == 1:
                        self._selected_domain = integrations[0]
                    elif requested_domain:
                        # Caller specified which integration to install
                        if requested_domain not in integrations:
                            return self.async_abort(
                                reason="domain_not_in_pr",
                                description_placeholders={
                                    "domain": requested_domain,
                                    "integrations": ", ".join(integrations),
                                },
                            )
                        self._selected_domain = requested_domain
                    else:
                        return self.async_abort(
                            reason="multiple_integrations_found",
                            description_placeholders={
                                "integrations": ", ".join(integrations),
                            },
                        )
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
        1. Already tracked by Integration Tester → confirm overwrite (auto-remove if
           overwrite=True). For import flows without overwrite, abort with clear error.
        2. Folder exists with our marker (switching reference) → proceed
        3. Folder exists but not managed by us → confirm overwrite in UI, or proceed
           if overwrite=True from service. For import flows without overwrite, abort.
        """
        await self.async_set_unique_id(self._selected_domain)
        is_import = self.context.get("source") == "import"

        # Check for existing Integration Tester entry with same unique ID
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == self.unique_id:
                # If overwrite was requested (from service), remove existing and proceed
                if self._overwrite_existing:
                    self._existing_entry_to_remove = entry
                    return await self._remove_existing_and_create()
                # For import flows, abort with clear error instead of form
                if is_import:
                    return self.async_abort(
                        reason="already_configured",
                        description_placeholders={
                            "domain": self._selected_domain,
                            "existing_url": entry.data.get(CONF_URL, ""),
                        },
                    )
                # For UI flows, show confirmation step
                self._existing_entry_to_remove = entry
                return await self.async_step_confirm_entry_overwrite()

        # Check if folder exists
        if integration_exists(self.hass, self._selected_domain):
            if integration_has_marker(self.hass, self._selected_domain):
                # We manage it, can proceed (switching reference)
                return await self._create_entry()
            # Overwrite requested — proceed (files will be replaced on install)
            if self._overwrite_existing:
                return await self._create_entry()
            # For import flows, abort with clear error
            if is_import:
                return self.async_abort(
                    reason="folder_exists",
                    description_placeholders={"domain": self._selected_domain},
                )
            # For UI flows, show confirmation
            return await self.async_step_confirm_overwrite()

        return await self._create_entry()

    async def async_step_confirm_overwrite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle confirmation to overwrite existing integration files (not managed by us)."""
        if user_input is not None:
            if user_input.get("confirm"):
                return await self._create_entry()
            return self.async_abort(reason="user_cancelled")

        return self.async_show_form(
            step_id="confirm_overwrite",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): cv.boolean,
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
            return self.async_abort(reason="user_cancelled")

        # Get info about existing entry for display
        existing_url = ""
        if self._existing_entry_to_remove:
            existing_url = self._existing_entry_to_remove.data.get(CONF_URL, "")

        return self.async_show_form(
            step_id="confirm_entry_overwrite",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): cv.boolean,
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

        name = (
            self._integration_info.name
            if self._integration_info
            else self._selected_domain
        )
        title = _build_title(
            name, self._resolved.reference_type, self._resolved.reference_value
        )

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

    def _reconfigure_placeholders(self, entry: ConfigEntry) -> dict[str, str]:
        """Get description placeholders shared by the reconfigure steps."""
        return {
            "domain": entry.data[CONF_INTEGRATION_DOMAIN],
            "url": entry.data[CONF_URL],
        }

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Page 1 of reconfigure: choose whether to track a branch, PR or commit."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        current_type = entry.data[CONF_REFERENCE_TYPE]

        if user_input is not None:
            current_type = user_input[CONF_REFERENCE_TYPE]
            if (
                entry.data.get(CONF_IS_PART_OF_HA_CORE, False)
                and current_type != ReferenceType.PR
            ):
                errors[CONF_REFERENCE_TYPE] = "core_requires_pr"
            else:
                self._reconfigure_type = ReferenceType(current_type)
                self._reference_options = None
                return await self.async_step_reconfigure_target()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFERENCE_TYPE, default=current_type
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[t.value for t in ReferenceType],
                            translation_key=CONF_REFERENCE_TYPE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=self._reconfigure_placeholders(entry),
        )

    async def async_step_reconfigure_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Page 2 of reconfigure: pick the target of the chosen type.

        Offers the most recently changed branches/PRs/commits in a dropdown plus a
        "(not listed)" entry that enables the free text field. A listed dropdown
        entry always takes precedence over the text field.
        """
        entry = self._get_reconfigure_entry()
        ref_type = self._reconfigure_type
        errors: dict[str, str] = {}
        placeholders = self._reconfigure_placeholders(entry)
        placeholders["target_type"] = REFERENCE_TYPE_NAMES[ref_type]
        parsed = parse_github_url(entry.data[CONF_URL])
        api = IntegrationTesterGitHubAPI(
            async_get_clientsession(self.hass),
            self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN),
        )

        if self._reference_options is None:
            try:
                self._reference_options = await api.list_recent_references(
                    parsed.owner, parsed.repo, ref_type
                )
            except GitHubAPIError as err:
                # Listing is a convenience; the text field still allows any target
                _LOGGER.warning("Could not list recent %ss: %s", ref_type.value, err)
                self._reference_options = []

        listed_values = {option.value for option in self._reference_options}
        same_type = ref_type.value == entry.data[CONF_REFERENCE_TYPE]
        current_value = entry.data[CONF_REFERENCE_VALUE] if same_type else None
        choice_default = (
            current_value if current_value in listed_values else REFERENCE_NOT_LISTED
        )
        custom_default: str | None = None

        if user_input is not None:
            choice = user_input[CONF_REFERENCE_CHOICE]
            custom_default = (user_input.get(CONF_CUSTOM_REFERENCE) or "").strip()
            choice_default = choice
            value = custom_default if choice == REFERENCE_NOT_LISTED else choice

            if choice == REFERENCE_NOT_LISTED and (
                not value
                or (ref_type == ReferenceType.PR and not value.isdigit())
                or (ref_type == ReferenceType.PR and int(value) < 1)
            ):
                errors[CONF_CUSTOM_REFERENCE] = "invalid_reference"
            elif same_type and value == current_value:
                return self.async_abort(reason="no_changes")
            else:
                validated = await self._async_validate_target(
                    entry,
                    api,
                    ref_type,
                    value,
                    errors=errors,
                    placeholders=placeholders,
                )
                if validated:
                    info, stored_value = validated
                    return self._async_apply_target(entry, info, ref_type, stored_value)
        elif current_value not in listed_values:
            custom_default = current_value

        options = [
            SelectOptionDict(value=option.value, label=option.label)
            for option in self._reference_options
        ]
        options.append(
            SelectOptionDict(value=REFERENCE_NOT_LISTED, label="(not listed)")
        )
        custom_key = vol.Optional(
            CONF_CUSTOM_REFERENCE,
            description={"suggested_value": custom_default} if custom_default else None,
        )
        return self.async_show_form(
            step_id="reconfigure_target",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFERENCE_CHOICE, default=choice_default
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            translation_key=CONF_REFERENCE_CHOICE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    custom_key: cv.string,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _async_validate_target(
        self,
        entry: ConfigEntry,
        api: IntegrationTesterGitHubAPI,
        ref_type: ReferenceType,
        value: str,
        *,
        errors: dict[str, str],
        placeholders: dict[str, str],
    ) -> tuple[IntegrationInfo, str] | None:
        """
        Check the target exists and provides the entry's integration.

        Returns the integration info and the value to store for the target. Commit
        targets are stored as the resolved full SHA so they stay pinned even if
        a branch or tag name was entered.
        """
        domain = entry.data[CONF_INTEGRATION_DOMAIN]
        is_core = entry.data.get(CONF_IS_PART_OF_HA_CORE, False)
        parsed = parse_github_url(entry.data[CONF_URL])
        try:
            resolved = await api.resolve_reference(
                ParsedGitHubURL(
                    owner=parsed.owner,
                    repo=parsed.repo,
                    reference_type=ref_type,
                    reference_value=value,
                    is_part_of_ha_core=is_core,
                )
            )
            stored_value = (
                resolved.commit_sha if ref_type == ReferenceType.COMMIT else value
            )
            if is_core:
                integrations = await api.get_core_pr_integrations(
                    resolved.owner, resolved.repo, int(value)
                )
                if domain not in integrations:
                    errors["base"] = "integration_not_in_pr"
                    placeholders["integrations"] = ", ".join(integrations)
                    return None
                info = await get_core_integration_info(
                    api, resolved.owner, resolved.repo, domain, resolved.commit_sha
                )
                return info, stored_value
            info = await validate_custom_integration(
                api,
                resolved.owner,
                resolved.repo,
                resolved.commit_sha,
                expected_domain=domain,
            )
            if info.domain != domain:
                errors["base"] = "domain_mismatch"
                placeholders["new_domain"] = info.domain
                return None
            return info, stored_value
        except ManifestNotFoundError:
            errors["base"] = "manifest_not_found"
        except IntegrationNotFoundError:
            errors["base"] = "integration_not_found"
        except GitHubAPIError as err:
            _LOGGER.error("GitHub API error during reconfigure: %s", err)
            errors["base"] = "github_error"
            placeholders["error"] = str(err)
        return None

    def _async_apply_target(
        self,
        entry: ConfigEntry,
        info: IntegrationInfo,
        ref_type: ReferenceType,
        value: str,
    ) -> ConfigFlowResult:
        """Store the new target and reload the entry to install it."""
        domain = entry.data[CONF_INTEGRATION_DOMAIN]
        # Dropping the installed commit makes setup download the new target
        data = {k: v for k, v in entry.data.items() if k != CONF_INSTALLED_COMMIT}
        data[CONF_REFERENCE_TYPE] = ref_type.value
        data[CONF_REFERENCE_VALUE] = value
        # Issues from the previous target no longer apply
        remove_pr_closed_issue(self.hass, domain)
        remove_integration_removed_issue(self.hass, domain)
        remove_download_failed_issue(self.hass, domain)
        return self.async_update_reload_and_abort(
            entry,
            title=_build_title(info.name, ref_type, value),
            data=data,
            reason="reconfigure_successful",
        )

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
