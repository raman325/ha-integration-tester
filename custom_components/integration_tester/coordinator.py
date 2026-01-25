"""Data update coordinator for Integration Tester."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IntegrationTesterGitHubAPI
from .const import (
    CONF_GITHUB_TOKEN,
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_IS_CORE_OR_FORK,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DATA_BRANCH_NAME,
    DATA_COMMIT_AUTHOR,
    DATA_COMMIT_DATE,
    DATA_COMMIT_MESSAGE,
    DATA_COMMIT_URL,
    DATA_CURRENT_COMMIT,
    DATA_INTEGRATION_NAME,
    DATA_IS_CORE_OR_FORK,
    DATA_LAST_PUSH,
    DATA_PR_AUTHOR,
    DATA_PR_NUMBER,
    DATA_PR_STATE,
    DATA_PR_TITLE,
    DATA_PR_URL,
    DATA_REPO_NAME,
    DATA_REPO_OWNER,
    DATA_REPO_URL,
    DATA_SOURCE_BRANCH,
    DATA_SOURCE_REPO_URL,
    DATA_TARGET_BRANCH,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    REPAIR_INTEGRATION_REMOVED,
    REPAIR_PR_CLOSED,
    CoordinatorData,
    PRState,
    ReferenceType,
)
from .exceptions import GitHubAPIError, GitHubAuthError
from .helpers import parse_github_url
from .repairs import (
    create_download_failed_issue,
    create_integration_removed_issue,
    create_pr_closed_issue,
    create_token_invalid_issue,
    is_repair_issue_acknowledged,
    remove_download_failed_issue,
    remove_token_invalid_issue,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class IntegrationTesterCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator for fetching integration update data from GitHub."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self._entry = entry
        self._api: IntegrationTesterGitHubAPI | None = None
        self._consecutive_failures = 0
        self._pr_closed_notified = False
        self._integration_removed_notified = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_INTEGRATION_DOMAIN]}",
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )

    @property
    def api(self) -> IntegrationTesterGitHubAPI:
        """Get the GitHub API client."""
        if self._api is None:
            session = async_get_clientsession(self.hass)
            token = self.hass.data.get(DOMAIN, {}).get(CONF_GITHUB_TOKEN)
            self._api = IntegrationTesterGitHubAPI(session, token)
        return self._api

    @property
    def reference_type(self) -> ReferenceType:
        """Get the reference type."""
        return ReferenceType(self._entry.data[CONF_REFERENCE_TYPE])

    @property
    def installed_commit(self) -> str:
        """Get the installed commit SHA."""
        return self._entry.data.get(CONF_INSTALLED_COMMIT, "")

    @property
    def domain(self) -> str:
        """Get the integration domain."""
        return self._entry.data[CONF_INTEGRATION_DOMAIN]

    @property
    def is_core_or_fork(self) -> bool:
        """Get whether this is a core integration or fork of core."""
        return self._entry.data.get(CONF_IS_CORE_OR_FORK, False)

    def _get_owner_repo(self) -> tuple[str, str]:
        """Get owner and repo from URL."""
        parsed = parse_github_url(self._entry.data[CONF_URL])
        return parsed.owner, parsed.repo

    async def _async_update_data(self) -> CoordinatorData:
        """
        Fetch data from GitHub API.

        Raises:
            UpdateFailed: If update fails.

        """
        owner, repo = self._get_owner_repo()
        ref_type = self.reference_type
        ref_value = self._entry.data[CONF_REFERENCE_VALUE]

        try:
            data: CoordinatorData = {}

            # Populate dynamic fields (derived from URL, may reflect renames)
            data[DATA_REPO_OWNER] = owner
            data[DATA_REPO_NAME] = repo
            data[DATA_REPO_URL] = f"https://github.com/{owner}/{repo}"
            data[DATA_IS_CORE_OR_FORK] = self.is_core_or_fork
            data[DATA_INTEGRATION_NAME] = self.domain  # Use domain as name for now

            if ref_type == ReferenceType.PR:
                pr_info = await self.api.get_pr_info(owner, repo, int(ref_value))

                data[DATA_CURRENT_COMMIT] = pr_info.head_sha
                data[DATA_PR_NUMBER] = pr_info.number
                data[DATA_PR_URL] = pr_info.html_url
                data[DATA_PR_TITLE] = pr_info.title
                data[DATA_PR_AUTHOR] = pr_info.author
                data[DATA_PR_STATE] = pr_info.state.value
                data[DATA_SOURCE_REPO_URL] = pr_info.source_repo_url
                data[DATA_SOURCE_BRANCH] = pr_info.source_branch
                data[DATA_TARGET_BRANCH] = pr_info.target_branch

                # Get commit info for the head
                commit_info = await self.api.get_commit_info(
                    owner, repo, pr_info.head_sha
                )
                data[DATA_COMMIT_MESSAGE] = commit_info.message
                data[DATA_COMMIT_AUTHOR] = commit_info.author
                data[DATA_COMMIT_DATE] = commit_info.date
                data[DATA_COMMIT_URL] = commit_info.html_url
                data[DATA_LAST_PUSH] = commit_info.date

                # Check PR state
                if pr_info.state in (PRState.CLOSED, PRState.MERGED):
                    self._handle_pr_closed(pr_info.state == PRState.MERGED)

                # For core PRs, check if integration still in diff
                if self.is_core_or_fork:
                    integrations = await self.api.get_core_pr_integrations(
                        owner, repo, int(ref_value)
                    )
                    if self.domain not in integrations:
                        self._handle_integration_removed()

            elif ref_type == ReferenceType.BRANCH:
                branch_info = await self.api.get_branch_info(owner, repo, ref_value)

                data[DATA_CURRENT_COMMIT] = branch_info.head_sha
                data[DATA_BRANCH_NAME] = branch_info.name
                data[DATA_COMMIT_MESSAGE] = branch_info.commit_message
                data[DATA_COMMIT_AUTHOR] = branch_info.commit_author
                data[DATA_COMMIT_DATE] = branch_info.commit_date
                data[DATA_LAST_PUSH] = branch_info.commit_date

                # Get commit URL
                commit_info = await self.api.get_commit_info(
                    owner, repo, branch_info.head_sha
                )
                data[DATA_COMMIT_URL] = commit_info.html_url

            else:  # COMMIT
                commit_info = await self.api.get_commit_info(owner, repo, ref_value)

                data[DATA_CURRENT_COMMIT] = commit_info.sha
                data[DATA_COMMIT_MESSAGE] = commit_info.message
                data[DATA_COMMIT_AUTHOR] = commit_info.author
                data[DATA_COMMIT_DATE] = commit_info.date
                data[DATA_COMMIT_URL] = commit_info.html_url
                data[DATA_LAST_PUSH] = commit_info.date

            # Success - reset failure counter and clear any issues
            self._consecutive_failures = 0
            remove_download_failed_issue(self.hass, self.domain)
            remove_token_invalid_issue(self.hass)

            return data

        except GitHubAuthError as err:
            # Token is invalid/expired/revoked - create global repair issue
            _LOGGER.error("GitHub authentication failed: %s", err)
            create_token_invalid_issue(self.hass)
            raise UpdateFailed(f"GitHub authentication failed: {err}") from err

        except GitHubAPIError as err:
            self._consecutive_failures += 1
            _LOGGER.warning(
                "Failed to fetch data for %s (attempt %d): %s",
                self.domain,
                self._consecutive_failures,
                err,
            )

            # After multiple failures, create repair issue
            if self._consecutive_failures >= 3:
                create_download_failed_issue(
                    self.hass, self._entry, self.domain, str(err)
                )

            raise UpdateFailed(f"Error fetching data: {err}") from err

    def _handle_pr_closed(self, is_merged: bool) -> None:
        """Handle PR being closed or merged."""
        issue_id = REPAIR_PR_CLOSED.format(domain=self.domain)

        # Create repair issue if not already done
        if not self._pr_closed_notified:
            create_pr_closed_issue(
                self.hass,
                self._entry,
                self.domain,
                int(self._entry.data[CONF_REFERENCE_VALUE]),
                is_merged,
            )
            self._pr_closed_notified = True

        # Send persistent notification if repair issue not acknowledged
        if not is_repair_issue_acknowledged(self.hass, issue_id):
            status = "merged" if is_merged else "closed"
            async_create_notification(
                self.hass,
                f"The PR for {self.domain} has been {status}. "
                f"Please remove this config entry to clean up.",
                title=f"Integration Tester: PR {status}",
                notification_id=f"integration_tester_pr_{self.domain}",
            )

    def _handle_integration_removed(self) -> None:
        """Handle integration being removed from diff."""
        issue_id = REPAIR_INTEGRATION_REMOVED.format(domain=self.domain)

        # Create repair issue if not already done
        if not self._integration_removed_notified:
            create_integration_removed_issue(self.hass, self._entry, self.domain)
            self._integration_removed_notified = True

        # Send persistent notification if repair issue not acknowledged
        if not is_repair_issue_acknowledged(self.hass, issue_id):
            async_create_notification(
                self.hass,
                f"The integration {self.domain} is no longer in the PR diff. "
                f"Please remove this config entry to clean up.",
                title="Integration Tester: Integration removed from PR",
                notification_id=f"integration_tester_removed_{self.domain}",
            )

    @property
    def update_available(self) -> bool:
        """Check if an update is available."""
        if not self.data:
            return False
        current_commit = self.data.get(DATA_CURRENT_COMMIT, "")
        return current_commit != self.installed_commit

    async def async_update_installed_commit(self, new_commit: str) -> None:
        """Update the installed commit in config entry."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_INSTALLED_COMMIT: new_commit},
        )
