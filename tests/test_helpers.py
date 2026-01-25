"""Tests for helpers module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiogithubapi.exceptions import (
    GitHubNotFoundException,
    GitHubRatelimitException,
)
import pytest

from custom_components.integration_tester.api import IntegrationTesterGitHubAPI
from custom_components.integration_tester.const import PRState, ReferenceType
from custom_components.integration_tester.exceptions import (
    GitHubAPIError,
    GitHubRateLimitError,
    InvalidGitHubURLError,
)
from custom_components.integration_tester.helpers import parse_github_url

from .conftest import create_mock_response


class TestParseGitHubURL:
    """Tests for parse_github_url function."""

    def test_parse_default_branch(self):
        """Test parsing a URL with default branch."""
        result = parse_github_url("https://github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.reference_type == ReferenceType.BRANCH
        assert result.reference_value is None
        assert not result.is_core_or_fork_repo

    def test_parse_default_branch_no_protocol(self):
        """Test parsing URL without protocol."""
        result = parse_github_url("github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_branch(self):
        """Test parsing a branch URL."""
        result = parse_github_url("https://github.com/owner/repo/tree/main")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.reference_type == ReferenceType.BRANCH
        assert result.reference_value == "main"

    def test_parse_branch_with_slashes(self):
        """Test parsing a branch URL with slashes in branch name."""
        result = parse_github_url(
            "https://github.com/owner/repo/tree/feature/my-feature"
        )
        assert result.reference_value == "feature/my-feature"

    def test_parse_pr(self):
        """Test parsing a PR URL."""
        result = parse_github_url("https://github.com/owner/repo/pull/123")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.reference_type == ReferenceType.PR
        assert result.reference_value == "123"

    def test_parse_commit(self):
        """Test parsing a commit URL."""
        result = parse_github_url("https://github.com/owner/repo/commit/abc123def")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.reference_type == ReferenceType.COMMIT
        assert result.reference_value == "abc123def"

    def test_parse_core_repo(self):
        """Test parsing Home Assistant core repo URL."""
        result = parse_github_url("https://github.com/home-assistant/core/pull/12345")
        assert result.owner == "home-assistant"
        assert result.repo == "core"
        assert result.is_core_or_fork_repo is True
        assert result.reference_type == ReferenceType.PR
        assert result.reference_value == "12345"

    def test_parse_with_trailing_slash(self):
        """Test parsing URL with trailing slash."""
        result = parse_github_url("https://github.com/owner/repo/")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_parse_with_www(self):
        """Test parsing URL with www prefix."""
        result = parse_github_url("https://www.github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_invalid_url(self):
        """Test parsing invalid URL raises exception."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("not-a-valid-url")

    def test_invalid_github_url(self):
        """Test parsing non-GitHub URL raises exception."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://gitlab.com/owner/repo")


class TestIntegrationTesterGitHubAPI:
    """Tests for IntegrationTesterGitHubAPI class."""

    @pytest.mark.asyncio
    async def test_get_pr_info(self, pr_response: dict[str, Any]):
        """Test getting PR info."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Set PR to open state for this test (fixture has closed state)
            pr_response["state"] = "open"
            pr_response["merged"] = False

            # aiogithubapi returns dict data via generic()
            mock_response = create_mock_response(pr_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_pr_info("raman325", "lock_code_manager", 1)

        assert result.number == 1
        assert result.title == "Configure Renovate"
        assert result.author == "renovate[bot]"
        assert result.head_sha == "e937d69acdeab0dc5eba5dbbc3418d78f4459533"
        assert result.state == PRState.OPEN

    @pytest.mark.asyncio
    async def test_get_pr_info_merged(self, pr_response: dict[str, Any]):
        """Test getting merged PR info."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Mark PR as merged
            pr_response["merged"] = True
            pr_response["state"] = "closed"
            mock_response = create_mock_response(pr_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_pr_info("owner", "repo", 1)

        assert result.state == PRState.MERGED

    @pytest.mark.asyncio
    async def test_get_commit_info(self, commit_response: dict[str, Any]):
        """Test getting commit info."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response(commit_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_commit_info("raman325", "lock_code_manager", "main")

        assert result.sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"
        assert "ruff" in result.message.lower()

    @pytest.mark.asyncio
    async def test_get_branch_info(self, branch_response: dict[str, Any]):
        """Test getting branch info."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response(branch_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_branch_info("raman325", "lock_code_manager", "main")

        assert result.name == "main"
        assert result.head_sha == "dbfc180aed0a16c253c1563023b069d5bf3ebcd3"

    @pytest.mark.asyncio
    async def test_get_core_pr_integrations(
        self, core_pr_files_response: list[dict[str, Any]]
    ):
        """Test getting integrations from core PR."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            # Set up paginated response for PR files
            # First page returns all files, second page returns empty
            page1_response = create_mock_response(core_pr_files_response)
            page2_response = create_mock_response([])
            mock_client.generic = AsyncMock(
                side_effect=[page1_response, page2_response]
            )

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_core_pr_integrations(
                "home-assistant", "core", 134000
            )

        assert "niko_home_control" in result

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test rate limit error handling."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            error = GitHubRatelimitException("Rate limit exceeded")
            mock_client.generic = AsyncMock(side_effect=error)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            with pytest.raises(GitHubRateLimitError):
                await api.get_pr_info("owner", "repo", 1)

    @pytest.mark.asyncio
    async def test_not_found_error(self):
        """Test 404 error handling."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            error = GitHubNotFoundException("Not Found")
            mock_client.generic = AsyncMock(side_effect=error)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            with pytest.raises(GitHubAPIError, match="not found"):
                await api.get_pr_info("owner", "repo", 999)

    @pytest.mark.asyncio
    async def test_with_token(self, pr_response: dict[str, Any]):
        """Test API with authentication token."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response(pr_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session, token="test-token")
            await api.get_pr_info("owner", "repo", 1)

            # Verify GitHub was instantiated with token and session
            mock_github_cls.assert_called_once_with(token="test-token", session=session)

    @pytest.mark.asyncio
    async def test_without_token(self, pr_response: dict[str, Any]):
        """Test API without authentication token."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response(pr_response)
            mock_client.generic = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)  # No token
            await api.get_pr_info("owner", "repo", 1)

            # Verify GitHub was instantiated without a token
            mock_github_cls.assert_called_once_with(token=None, session=session)

    @pytest.mark.asyncio
    async def test_download_archive(self):
        """Test downloading archive."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response(b"tarball content")
            mock_client.repos.tarball = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.download_archive("owner", "repo", "main")

        assert result == b"tarball content"

    @pytest.mark.asyncio
    async def test_file_exists_true(self):
        """Test file_exists returns True when file exists."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_response = create_mock_response({"content": "test"})
            mock_client.repos.contents.get = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.file_exists("owner", "repo", "path/to/file")

        assert result is True

    @pytest.mark.asyncio
    async def test_file_exists_false(self):
        """Test file_exists returns False when file doesn't exist."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            error = GitHubNotFoundException("Not found")
            mock_client.repos.contents.get = AsyncMock(side_effect=error)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.file_exists("owner", "repo", "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_default_branch(self):
        """Test getting default branch."""
        with patch(
            "custom_components.integration_tester.api.GitHubAPI"
        ) as mock_github_cls:
            mock_client = MagicMock()
            mock_github_cls.return_value = mock_client

            mock_data = MagicMock()
            mock_data.default_branch = "main"
            mock_response = create_mock_response(mock_data)
            mock_client.repos.get = AsyncMock(return_value=mock_response)

            session = MagicMock()
            api = IntegrationTesterGitHubAPI(session)
            result = await api.get_default_branch("owner", "repo")

        assert result == "main"
