"""Data models for Integration Tester."""

from __future__ import annotations

from dataclasses import dataclass

from .const import PRState, ReferenceType


@dataclass
class ParsedGitHubURL:
    """Parsed GitHub URL information."""

    owner: str
    repo: str
    reference_type: ReferenceType
    reference_value: str | None  # None for default branch
    is_core_or_fork_repo: bool

    @property
    def repo_url(self) -> str:
        """Return the full repository URL."""
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class PRInfo:
    """Information about a pull request."""

    number: int
    title: str
    state: PRState
    author: str
    head_sha: str
    head_ref: str
    source_repo_url: str | None  # None if same repo (not a fork)
    source_branch: str
    target_branch: str
    html_url: str


@dataclass
class CommitInfo:
    """Information about a commit."""

    sha: str
    message: str
    author: str
    date: str
    html_url: str


@dataclass
class BranchInfo:
    """Information about a branch."""

    name: str
    head_sha: str
    commit_message: str
    commit_author: str
    commit_date: str


@dataclass
class IntegrationInfo:
    """Information about an integration."""

    domain: str
    name: str
    is_core_or_fork: bool


@dataclass(kw_only=True)
class ResolvedReference(ParsedGitHubURL):
    """Resolved git reference with all context needed for the config flow.

    Inherits from ParsedGitHubURL and adds the resolved commit SHA and
    type-specific metadata. After resolution, reference_value is always set
    (never None).
    """

    # Resolved commit SHA
    commit_sha: str

    # Type-specific info (one will be populated based on reference_type)
    pr_info: PRInfo | None = None
    branch_info: BranchInfo | None = None
    commit_info: CommitInfo | None = None
