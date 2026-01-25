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
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_CORE_OR_FORK,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
)
from .exceptions import (
    GitHubAPIError,
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

_LOGGER = logging.getLogger(__name__)


class IntegrationTesterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Integration Tester."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api: IntegrationTesterGitHubAPI | None = None
        self._resolved: ResolvedReference | None = None
        self._integration_info: IntegrationInfo | None = None
        self._available_integrations: list[str] = []
        self._selected_domain: str | None = None

    def _get_user_schema(self) -> vol.Schema:
        """Get the schema for the user step, including token field if not configured."""
        schema = {vol.Required("url"): cv.string}

        # Require token if not already configured
        if not self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN):
            schema[vol.Required(CONF_GITHUB_TOKEN)] = cv.string

        return vol.Schema(schema)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store token if provided
            if token := user_input.get(CONF_GITHUB_TOKEN):
                self.hass.data.setdefault(DOMAIN, {})[CONF_GITHUB_TOKEN] = token

            try:
                parsed_url = parse_github_url(user_input["url"])
            except InvalidGitHubURLError:
                errors["url"] = "invalid_url"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(),
                    errors=errors,
                )

            # Initialize API client
            session = async_get_clientsession(self.hass)
            token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN)
            self._api = IntegrationTesterGitHubAPI(session, token)

            try:
                # Resolve the reference to get commit SHA and all context
                self._resolved = await self._api.resolve_reference(parsed_url)

                # Handle core vs external repos differently
                if self._resolved.is_core_or_fork_repo:
                    return await self._handle_core_repo(self._resolved.commit_sha)
                else:
                    return await self._handle_external_repo(self._resolved.commit_sha)

            except GitHubAPIError as err:
                _LOGGER.error("GitHub API error: %s", err)
                errors["url"] = "github_error"

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_user_schema(),
            errors=errors,
        )

    async def _handle_core_repo(self, ref: str) -> ConfigFlowResult:
        """Handle core repository URL."""
        # Get integrations modified in this PR/branch/commit
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

    async def _handle_external_repo(self, ref: str) -> ConfigFlowResult:
        """Handle external repository URL."""
        try:
            self._integration_info = await validate_custom_integration(
                self._api,
                self._resolved.owner,
                self._resolved.repo,
                ref,
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
        """Check if integration already exists and handle conflicts."""
        await self.async_set_unique_id(self._selected_domain)

        # Check for existing Integration Tester entry with same unique ID
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == self.unique_id:
                if entry.data[CONF_URL] == self._resolved.repo_url:
                    return self.async_abort(reason="already_configured_same_repo")
                return self.async_abort(reason="already_configured_different_repo")

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
        """Handle confirmation to overwrite existing integration."""
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

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry."""
        # Get integration info if not already set
        if self._integration_info is None and self._resolved.is_core_or_fork_repo:
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
        data = {
            CONF_URL: self._resolved.repo_url,
            CONF_REFERENCE_TYPE: self._resolved.reference_type.value,
            CONF_REFERENCE_VALUE: self._resolved.reference_value,
            CONF_INTEGRATION_DOMAIN: self._selected_domain,
            CONF_INSTALLED_COMMIT: self._get_current_ref(),
            CONF_IS_CORE_OR_FORK: self._resolved.is_core_or_fork_repo,
        }

        return self.async_create_entry(title=title, data=data)

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
        if user_input is not None:
            # Store token in hass.data for use by API client
            token = user_input.get(CONF_GITHUB_TOKEN)
            if token:
                self.hass.data.setdefault(DOMAIN, {})[CONF_GITHUB_TOKEN] = token
            elif CONF_GITHUB_TOKEN in self.hass.data.get(DOMAIN, {}):
                del self.hass.data[DOMAIN][CONF_GITHUB_TOKEN]

            return self.async_create_entry(title="", data=user_input)

        current_token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_GITHUB_TOKEN, default=current_token): cv.string,
                }
            ),
            description_placeholders={
                "domain": self._config_entry.data.get(CONF_INTEGRATION_DOMAIN, ""),
            },
        )
