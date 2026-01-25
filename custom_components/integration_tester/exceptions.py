"""Exceptions for Integration Tester."""

from homeassistant.exceptions import HomeAssistantError


class IntegrationTesterError(HomeAssistantError):
    """Base exception for Integration Tester."""


class InvalidGitHubURLError(IntegrationTesterError):
    """Raised when a GitHub URL cannot be parsed."""


class GitHubAPIError(IntegrationTesterError):
    """Raised when GitHub API request fails."""


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded."""


class GitHubAuthError(GitHubAPIError):
    """Raised when GitHub API authentication fails (invalid/expired/revoked token)."""


class ManifestNotFoundError(IntegrationTesterError):
    """Raised when manifest.json is not found."""


class IntegrationNotFoundError(IntegrationTesterError):
    """Raised when integration is not found in repository."""


class IntegrationAlreadyExistsError(IntegrationTesterError):
    """Raised when integration already exists and is not managed by us."""


class DownloadError(IntegrationTesterError):
    """Raised when download fails."""
