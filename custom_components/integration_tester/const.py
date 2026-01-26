"""Constants for Integration Tester."""

from enum import StrEnum
from typing import Final, TypedDict

DOMAIN: Final = "integration_tester"

# Marker file to track which integrations we manage
MARKER_FILE: Final = ".integration_tester"

# GitHub
HA_CORE_REPO: Final = "home-assistant/core"
HA_CORE_COMPONENTS_PATH: Final = "homeassistant/components"

# Config entry data keys (minimal storage)
CONF_URL: Final = "url"
CONF_REFERENCE_TYPE: Final = "reference_type"
CONF_REFERENCE_VALUE: Final = "reference_value"
CONF_INTEGRATION_DOMAIN: Final = "integration_domain"
CONF_INSTALLED_COMMIT: Final = "installed_commit"
CONF_GITHUB_TOKEN: Final = "github_token"
CONF_IS_PART_OF_HA_CORE: Final = "is_part_of_ha_core"

# Coordinator data keys
DATA_COORDINATOR: Final = "coordinator"
DATA_REFERENCE_TYPE: Final = CONF_REFERENCE_TYPE
DATA_INTEGRATION_DOMAIN: Final = CONF_INTEGRATION_DOMAIN
DATA_REPO_OWNER: Final = "repo_owner"
DATA_REPO_NAME: Final = "repo_name"
DATA_REPO_URL: Final = "repo_url"
DATA_IS_PART_OF_HA_CORE: Final = CONF_IS_PART_OF_HA_CORE
DATA_INTEGRATION_NAME: Final = "integration_name"
DATA_COMMIT_HASH: Final = "commit_hash"
DATA_COMMIT_MESSAGE: Final = "commit_message"
DATA_COMMIT_AUTHOR: Final = "commit_author"
DATA_COMMIT_DATE: Final = "commit_date"
DATA_COMMIT_URL: Final = "commit_url"
DATA_LAST_PUSH: Final = "last_push"
DATA_BRANCH_NAME: Final = "branch_name"
DATA_BRANCH_URL: Final = "branch_url"
DATA_PR_NUMBER: Final = "pr_number"
DATA_PR_URL: Final = "pr_url"
DATA_PR_TITLE: Final = "pr_title"
DATA_PR_AUTHOR: Final = "pr_author"
DATA_PR_STATE: Final = "pr_state"
DATA_SOURCE_REPO_URL: Final = "source_repo_url"
DATA_SOURCE_BRANCH: Final = "source_branch"
DATA_TARGET_BRANCH: Final = "target_branch"


class CoordinatorData(TypedDict, total=False):
    """Type definition for coordinator data.

    Different reference types populate different keys:
    - All types: repo_owner, repo_name, repo_url, is_part_of_ha_core, integration_name,
                 commit_hash, commit_message, commit_author, commit_date,
                 commit_url, last_push
    - PR only: pr_number, pr_url, pr_title, pr_author, pr_state,
               source_repo_url, source_branch, target_branch
    - Branch only: branch_name, branch_url
    """

    # Dynamic fields (refreshed from API, may change if repo renamed/transferred)
    repo_owner: str
    repo_name: str
    repo_url: str
    is_part_of_ha_core: bool
    integration_name: str

    # Common fields (present for all reference types)
    commit_hash: str
    commit_message: str
    commit_author: str
    commit_date: str
    commit_url: str
    last_push: str

    # PR-specific fields
    pr_number: int
    pr_url: str
    pr_title: str
    pr_author: str
    pr_state: str
    source_repo_url: str
    source_branch: str
    target_branch: str

    # Branch-specific fields
    branch_name: str
    branch_url: str


# Defaults
DEFAULT_UPDATE_INTERVAL: Final = 300  # 5 minutes in seconds
RETRY_BACKOFF_BASE: Final = 60  # Base retry interval in seconds
MAX_RETRIES: Final = 5


class ReferenceType(StrEnum):
    """Type of Git reference being tracked."""

    COMMIT = "commit"
    BRANCH = "branch"
    PR = "pr"


class PRState(StrEnum):
    """State of a pull request."""

    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


# Repair issue IDs
REPAIR_RESTART_REQUIRED: Final = "restart_required_{domain}"
REPAIR_PR_CLOSED: Final = "pr_closed_{domain}"
REPAIR_INTEGRATION_REMOVED: Final = "integration_removed_{domain}"
REPAIR_DOWNLOAD_FAILED: Final = "download_failed_{domain}"
REPAIR_TOKEN_INVALID: Final = "token_invalid"  # Global, not per-domain
