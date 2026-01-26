"""Tests for GitHub API client."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiogithubapi.exceptions import (
    GitHubAuthenticationException,
    GitHubNotFoundException,
    GitHubRatelimitException,
)
import pytest

from custom_components.integration_tester.api import IntegrationTesterGitHubAPI
from custom_components.integration_tester.const import PRState, ReferenceType
from custom_components.integration_tester.exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
)
from custom_components.integration_tester.models import ParsedGitHubURL

from .conftest import create_mock_response


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    return MagicMock()


@pytest.fixture
def api_and_client(mock_session):
    """Create an API client instance with mocked GitHubAPI, returning both."""
    with patch("custom_components.integration_tester.api.GitHubAPI") as mock_github_cls:
        mock_client = MagicMock()
        mock_client.repos = MagicMock()
        mock_client.repos.contents = MagicMock()
        mock_github_cls.return_value = mock_client
        api_instance = IntegrationTesterGitHubAPI(mock_session, token="test_token")
        yield api_instance, mock_client


class TestGetPRInfo:
    """Tests for get_pr_info using fixture data."""

    @pytest.mark.asyncio
    async def test_get_pr_info_closed_not_merged(
        self, api_and_client, pr_response: dict[str, Any]
    ):
        """Test getting info for a closed (not merged) PR using fixture data."""
        api, mock_client = api_and_client
        # pr_response fixture has state=closed and merged_at=null
        mock_client.generic = AsyncMock(return_value=create_mock_response(pr_response))

        result = await api.get_pr_info("raman325", "lock_code_manager", 1)

        assert result.number == 1
        assert result.title == "Configure Renovate"
        assert result.state == PRState.CLOSED  # closed but not merged
        assert result.author == "renovate[bot]"
        assert result.head_sha == "e937d69acdeab0dc5eba5dbbc3418d78f4459533"
        assert result.head_ref == "renovate/configure"

    @pytest.mark.asyncio
    async def test_get_pr_info_open(self, api_and_client, pr_response: dict[str, Any]):
        """Test getting info for an open PR."""
        api, mock_client = api_and_client
        pr_response["state"] = "open"
        pr_response["merged"] = False
        mock_client.generic = AsyncMock(return_value=create_mock_response(pr_response))

        result = await api.get_pr_info("raman325", "lock_code_manager", 1)

        assert result.state == PRState.OPEN

    @pytest.mark.asyncio
    async def test_get_pr_info_merged(
        self, api_and_client, pr_response: dict[str, Any]
    ):
        """Test getting info for a merged PR."""
        api, mock_client = api_and_client
        pr_response["state"] = "closed"
        pr_response["merged"] = True
        mock_client.generic = AsyncMock(return_value=create_mock_response(pr_response))

        result = await api.get_pr_info("raman325", "lock_code_manager", 1)

        assert result.state == PRState.MERGED

    @pytest.mark.asyncio
    async def test_get_pr_info_from_fork(
        self, api_and_client, pr_response: dict[str, Any]
    ):
        """Test getting info for a PR from a fork detects source_repo_url."""
        api, mock_client = api_and_client
        # Modify head repo to differ from base repo to simulate fork
        pr_response["head"]["repo"]["full_name"] = "forker/lock_code_manager"
        pr_response["head"]["repo"]["html_url"] = (
            "https://github.com/forker/lock_code_manager"
        )
        mock_client.generic = AsyncMock(return_value=create_mock_response(pr_response))

        result = await api.get_pr_info("raman325", "lock_code_manager", 1)

        assert result.source_repo_url == "https://github.com/forker/lock_code_manager"

    @pytest.mark.asyncio
    async def test_get_pr_info_auth_error(self, api_and_client):
        """Test auth error handling."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubAuthenticationException("Invalid token")
        )

        with pytest.raises(GitHubAuthError):
            await api.get_pr_info("owner", "repo", 123)

    @pytest.mark.asyncio
    async def test_get_pr_info_rate_limit(self, api_and_client):
        """Test rate limit error handling."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.get_pr_info("owner", "repo", 123)

    @pytest.mark.asyncio
    async def test_get_pr_info_not_found(self, api_and_client):
        """Test not found error handling."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubNotFoundException("Not found")
        )

        with pytest.raises(GitHubAPIError, match="not found"):
            await api.get_pr_info("owner", "repo", 123)


class TestGetCommitInfo:
    """Tests for get_commit_info using fixture data."""

    @pytest.mark.asyncio
    async def test_get_commit_info(
        self, api_and_client, commit_response: dict[str, Any]
    ):
        """Test getting commit info using fixture data."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(commit_response)
        )

        result = await api.get_commit_info("raman325", "lock_code_manager", "main")

        assert result.sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
        assert "ruff" in result.message.lower()  # First line of commit message
        assert result.author == "dependabot[bot]"  # From fixture data

    @pytest.mark.asyncio
    async def test_get_commit_info_rate_limit(self, api_and_client):
        """Test rate limit error."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.get_commit_info("owner", "repo", "abc123")

    @pytest.mark.asyncio
    async def test_get_commit_info_not_found(self, api_and_client):
        """Test not found error."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubNotFoundException("Not found")
        )

        with pytest.raises(GitHubAPIError, match="Commit.*not found"):
            await api.get_commit_info("owner", "repo", "abc123")


class TestGetBranchInfo:
    """Tests for get_branch_info using fixture data."""

    @pytest.mark.asyncio
    async def test_get_branch_info(
        self, api_and_client, branch_response: dict[str, Any]
    ):
        """Test getting branch info using fixture data."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(branch_response)
        )

        result = await api.get_branch_info("raman325", "lock_code_manager", "main")

        assert result.name == "main"
        assert result.head_sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
        assert "ruff" in result.commit_message.lower()

    @pytest.mark.asyncio
    async def test_get_branch_info_rate_limit(self, api_and_client):
        """Test rate limit error."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.get_branch_info("owner", "repo", "main")

    @pytest.mark.asyncio
    async def test_get_branch_info_not_found(self, api_and_client):
        """Test not found error."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubNotFoundException("Not found")
        )

        with pytest.raises(GitHubAPIError, match="Branch.*not found"):
            await api.get_branch_info("owner", "repo", "nonexistent")


class TestGetDefaultBranch:
    """Tests for get_default_branch."""

    @pytest.mark.asyncio
    async def test_get_default_branch(self, api_and_client):
        """Test getting default branch."""
        api, mock_client = api_and_client
        mock_repo = MagicMock()
        mock_repo.data.default_branch = "develop"
        mock_client.repos.get = AsyncMock(return_value=mock_repo)

        result = await api.get_default_branch("owner", "repo")

        assert result == "develop"

    @pytest.mark.asyncio
    async def test_get_default_branch_rate_limit(self, api_and_client):
        """Test rate limit error."""
        api, mock_client = api_and_client
        mock_client.repos.get = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.get_default_branch("owner", "repo")


class TestIsCoreOrFork:
    """Tests for is_core_or_fork."""

    @pytest.mark.asyncio
    async def test_is_core_direct_match(self, api_and_client):
        """Test direct match of home-assistant/core."""
        api, _ = api_and_client
        # No API call needed for direct match
        result = await api.is_core_or_fork("home-assistant", "core")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_core_fork(self, api_and_client):
        """Test detection of HA core fork via parent check."""
        api, mock_client = api_and_client
        mock_repo = MagicMock()
        mock_repo.data.fork = True
        mock_repo.data.parent = MagicMock()
        mock_repo.data.parent.full_name = "home-assistant/core"
        mock_client.repos.get = AsyncMock(return_value=mock_repo)

        result = await api.is_core_or_fork("user", "my-fork")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_not_core_or_fork(self, api_and_client):
        """Test non-core repository."""
        api, mock_client = api_and_client
        mock_repo = MagicMock()
        mock_repo.data.fork = False
        mock_client.repos.get = AsyncMock(return_value=mock_repo)

        result = await api.is_core_or_fork("user", "custom-integration")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_core_or_fork_rate_limit(self, api_and_client):
        """Test rate limit error."""
        api, mock_client = api_and_client
        mock_client.repos.get = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.is_core_or_fork("user", "repo")


class TestGetPRFiles:
    """Tests for get_pr_files using fixture data."""

    @pytest.mark.asyncio
    async def test_get_pr_files(
        self, api_and_client, core_pr_files_response: list[dict[str, Any]]
    ):
        """Test getting PR files using fixture data."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(core_pr_files_response)
        )

        result = await api.get_pr_files("home-assistant", "core", 134000)

        # Fixture has files for niko_home_control
        assert any("niko_home_control" in f for f in result)

    @pytest.mark.asyncio
    async def test_get_pr_files_pagination(self, api_and_client):
        """Test PR files with pagination."""
        api, mock_client = api_and_client
        page1 = [{"filename": f"file{i}.py"} for i in range(100)]
        page2 = [{"filename": "last_file.py"}]

        call_count = 0

        async def mock_generic_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return create_mock_response(page1)
            return create_mock_response(page2)

        mock_client.generic = mock_generic_fn

        result = await api.get_pr_files("owner", "repo", 123)

        assert len(result) == 101
        assert result[-1] == "last_file.py"

    @pytest.mark.asyncio
    async def test_get_pr_files_auth_error(self, api_and_client):
        """Test auth error."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            side_effect=GitHubAuthenticationException("Invalid token")
        )

        with pytest.raises(GitHubAuthError):
            await api.get_pr_files("owner", "repo", 123)


class TestDownloadArchive:
    """Tests for download_archive."""

    @pytest.mark.asyncio
    async def test_download_archive(self, api_and_client):
        """Test downloading archive."""
        api, mock_client = api_and_client
        archive_data = b"fake_tarball_data"
        mock_response = MagicMock()
        mock_response.data = archive_data
        mock_client.repos.tarball = AsyncMock(return_value=mock_response)

        result = await api.download_archive("owner", "repo", "abc123")

        assert result == archive_data
        mock_client.repos.tarball.assert_called_once_with("owner/repo", ref="abc123")

    @pytest.mark.asyncio
    async def test_download_archive_auth_error(self, api_and_client):
        """Test auth error."""
        api, mock_client = api_and_client
        mock_client.repos.tarball = AsyncMock(
            side_effect=GitHubAuthenticationException("Invalid token")
        )

        with pytest.raises(GitHubAuthError):
            await api.download_archive("owner", "repo", "abc123")

    @pytest.mark.asyncio
    async def test_download_archive_rate_limit(self, api_and_client):
        """Test rate limit error."""
        api, mock_client = api_and_client
        mock_client.repos.tarball = AsyncMock(
            side_effect=GitHubRatelimitException("Rate limited")
        )

        with pytest.raises(GitHubRateLimitError):
            await api.download_archive("owner", "repo", "abc123")


class TestGetCorePRIntegrations:
    """Tests for get_core_pr_integrations using fixture data."""

    @pytest.mark.asyncio
    async def test_get_core_pr_integrations(
        self, api_and_client, core_pr_files_response: list[dict[str, Any]]
    ):
        """Test extracting integration domains from PR files."""
        api, mock_client = api_and_client
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(core_pr_files_response)
        )

        result = await api.get_core_pr_integrations("home-assistant", "core", 134000)

        assert "niko_home_control" in result  # From fixture data


class TestResolveReference:
    """Tests for resolve_reference."""

    @pytest.mark.asyncio
    async def test_resolve_pr_reference(
        self, api_and_client, pr_response: dict[str, Any]
    ):
        """Test resolving a PR reference."""
        api, mock_client = api_and_client
        parsed_url = ParsedGitHubURL(
            owner="raman325",
            repo="lock_code_manager",
            reference_type=ReferenceType.PR,
            reference_value="1",
            is_core_or_fork_repo=False,
        )

        # Mock is_core_or_fork to return False (not a core repo)
        mock_repo = MagicMock()
        mock_repo.data.fork = False
        mock_client.repos.get = AsyncMock(return_value=mock_repo)
        mock_client.generic = AsyncMock(return_value=create_mock_response(pr_response))

        result = await api.resolve_reference(parsed_url)

        assert result.commit_sha == "e937d69acdeab0dc5eba5dbbc3418d78f4459533"
        assert result.reference_type == ReferenceType.PR
        assert result.pr_info is not None

    @pytest.mark.asyncio
    async def test_resolve_branch_reference(
        self, api_and_client, branch_response: dict[str, Any]
    ):
        """Test resolving a branch reference."""
        api, mock_client = api_and_client
        parsed_url = ParsedGitHubURL(
            owner="raman325",
            repo="lock_code_manager",
            reference_type=ReferenceType.BRANCH,
            reference_value="main",
            is_core_or_fork_repo=False,
        )

        mock_repo = MagicMock()
        mock_repo.data.fork = False
        mock_client.repos.get = AsyncMock(return_value=mock_repo)
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(branch_response)
        )

        result = await api.resolve_reference(parsed_url)

        assert result.commit_sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
        assert result.reference_type == ReferenceType.BRANCH
        assert result.branch_info is not None

    @pytest.mark.asyncio
    async def test_resolve_default_branch_reference(
        self, api_and_client, branch_response: dict[str, Any]
    ):
        """Test resolving default branch (None value)."""
        api, mock_client = api_and_client
        parsed_url = ParsedGitHubURL(
            owner="owner",
            repo="repo",
            reference_type=ReferenceType.BRANCH,
            reference_value=None,  # Default branch
            is_core_or_fork_repo=False,
        )

        # Mock for is_core_or_fork and get_default_branch
        mock_repo = MagicMock()
        mock_repo.data.fork = False
        mock_repo.data.default_branch = "main"
        mock_client.repos.get = AsyncMock(return_value=mock_repo)
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(branch_response)
        )

        result = await api.resolve_reference(parsed_url)

        assert result.branch_info is not None

    @pytest.mark.asyncio
    async def test_resolve_commit_reference(
        self, api_and_client, commit_response: dict[str, Any]
    ):
        """Test resolving a commit reference."""
        api, mock_client = api_and_client
        parsed_url = ParsedGitHubURL(
            owner="raman325",
            repo="lock_code_manager",
            reference_type=ReferenceType.COMMIT,
            reference_value="dbfc180",
            is_core_or_fork_repo=False,
        )

        mock_repo = MagicMock()
        mock_repo.data.fork = False
        mock_client.repos.get = AsyncMock(return_value=mock_repo)
        mock_client.generic = AsyncMock(
            return_value=create_mock_response(commit_response)
        )

        result = await api.resolve_reference(parsed_url)

        assert result.commit_sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
        assert result.reference_type == ReferenceType.COMMIT
        assert result.commit_info is not None


class TestGetFileContent:
    """Tests for get_file_content."""

    @pytest.mark.asyncio
    async def test_get_file_content_base64(self, api_and_client):
        """Test getting file content with base64 encoding."""
        api, mock_client = api_and_client
        content = "print('hello world')"
        encoded = base64.b64encode(content.encode()).decode()

        mock_data = MagicMock()
        mock_data.content = encoded
        mock_data.encoding = "base64"
        mock_response = MagicMock()
        mock_response.data = mock_data
        mock_client.repos.contents.get = AsyncMock(return_value=mock_response)

        result = await api.get_file_content("owner", "repo", "test.py")

        assert result == content

    @pytest.mark.asyncio
    async def test_get_file_content_not_found(self, api_and_client):
        """Test file not found error."""
        api, mock_client = api_and_client
        mock_client.repos.contents.get = AsyncMock(
            side_effect=GitHubNotFoundException("Not found")
        )

        with pytest.raises(GitHubAPIError, match="not found"):
            await api.get_file_content("owner", "repo", "missing.py")


class TestGetDirectoryContents:
    """Tests for get_directory_contents."""

    @pytest.mark.asyncio
    async def test_get_directory_contents(self, api_and_client):
        """Test getting directory contents."""
        api, mock_client = api_and_client
        # Directory listing returns a list
        # MagicMock's `name` param names the mock itself, so set name as attribute
        item1 = MagicMock()
        item1.name = "file1.py"
        item1.type = "file"
        item2 = MagicMock()
        item2.name = "subdir"
        item2.type = "dir"
        mock_response = MagicMock()
        mock_response.data = [item1, item2]
        mock_client.repos.contents.get = AsyncMock(return_value=mock_response)

        result = await api.get_directory_contents("owner", "repo", "src")

        assert len(result) == 2
        assert result[0]["name"] == "file1.py"
        assert result[0]["type"] == "file"
        assert result[1]["name"] == "subdir"
        assert result[1]["type"] == "dir"

    @pytest.mark.asyncio
    async def test_get_directory_contents_not_a_directory(self, api_and_client):
        """Test error when path is not a directory."""
        api, mock_client = api_and_client
        # Single file returns an object, not a list
        mock_data = MagicMock()
        mock_response = MagicMock()
        mock_response.data = mock_data
        mock_client.repos.contents.get = AsyncMock(return_value=mock_response)

        with pytest.raises(GitHubAPIError, match="not a directory"):
            await api.get_directory_contents("owner", "repo", "file.py")
