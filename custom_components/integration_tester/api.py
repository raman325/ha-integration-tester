"""GitHub API client for Integration Tester."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from aiogithubapi import GitHubAPI
from aiogithubapi.exceptions import (
    GitHubAuthenticationException,
    GitHubException,
    GitHubNotFoundException,
    GitHubPermissionException,
    GitHubRatelimitException,
)

from .const import HA_CORE_COMPONENTS_PATH, HA_CORE_REPO, PRState, ReferenceType
from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError
from .models import BranchInfo, CommitInfo, ParsedGitHubURL, PRInfo, ResolvedReference

if TYPE_CHECKING:
    from aiohttp import ClientSession


class IntegrationTesterGitHubAPI:
    """GitHub API client using aiogithubapi with HA's aiohttp session."""

    def __init__(self, session: ClientSession, token: str | None = None) -> None:
        """Initialize the GitHub API client."""
        self._client = GitHubAPI(token=token, session=session)

    async def get_pr_info(self, owner: str, repo: str, pr_number: int) -> PRInfo:
        """
        Get information about a pull request.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        try:
            response = await self._client.generic(
                endpoint=f"/repos/{owner}/{repo}/pulls/{pr_number}"
            )
            data = response.data

            # Determine PR state
            if data.get("merged"):
                state = PRState.MERGED
            elif data.get("state") == "closed":
                state = PRState.CLOSED
            else:
                state = PRState.OPEN

            # Check if PR is from a fork
            source_repo_url = None
            head = data.get("head", {})
            base = data.get("base", {})
            head_repo = head.get("repo") or {}
            base_repo = base.get("repo") or {}
            if head_repo.get("full_name") != base_repo.get("full_name"):
                source_repo_url = head_repo.get("html_url")

            user = data.get("user") or {}

            return PRInfo(
                number=data.get("number", pr_number),
                title=data.get("title", ""),
                state=state,
                author=user.get("login", "unknown"),
                head_sha=head.get("sha", ""),
                head_ref=head.get("ref", ""),
                source_repo_url=source_repo_url,
                source_branch=head.get("ref", ""),
                target_branch=base.get("ref", ""),
                html_url=data.get("html_url", ""),
            )

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(
                f"Pull request {pr_number} not found in {owner}/{repo}"
            ) from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def get_commit_info(self, owner: str, repo: str, ref: str) -> CommitInfo:
        """
        Get information about a commit.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        try:
            response = await self._client.generic(
                endpoint=f"/repos/{owner}/{repo}/commits/{ref}"
            )
            data = response.data

            commit = data.get("commit", {})
            author = commit.get("author", {})

            return CommitInfo(
                sha=data.get("sha", ""),
                message=(commit.get("message") or "").split("\n")[0],
                author=author.get("name", "unknown"),
                date=author.get("date", ""),
                html_url=data.get("html_url", ""),
            )

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(f"Commit {ref} not found in {owner}/{repo}") from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def get_branch_info(self, owner: str, repo: str, branch: str) -> BranchInfo:
        """
        Get information about a branch.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        try:
            response = await self._client.generic(
                endpoint=f"/repos/{owner}/{repo}/branches/{branch}"
            )
            data = response.data

            commit_data = data.get("commit", {})
            commit = commit_data.get("commit", {})
            author = commit.get("author", {})

            return BranchInfo(
                name=data.get("name", branch),
                head_sha=commit_data.get("sha", ""),
                commit_message=(commit.get("message") or "").split("\n")[0],
                commit_author=author.get("name", "unknown"),
                commit_date=author.get("date", ""),
            )

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(
                f"Branch {branch} not found in {owner}/{repo}"
            ) from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def get_default_branch(self, owner: str, repo: str) -> str:
        """
        Get the default branch of a repository.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        try:
            response = await self._client.repos.get(f"{owner}/{repo}")
            return response.data.default_branch or "main"

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(f"Repository {owner}/{repo} not found") from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def is_core_or_fork(self, owner: str, repo: str) -> bool:
        """
        Check if a repository is home-assistant/core or a fork of it.

        Raises:
            GitHubAuthError: If authentication fails.
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        # Direct match
        if f"{owner}/{repo}" == HA_CORE_REPO:
            return True

        try:
            resp = await self._client.repos.get(f"{owner}/{repo}")
            # Check if it's a fork of home-assistant/core
            if resp.data.fork and hasattr(resp.data, "parent") and resp.data.parent:
                if getattr(resp.data.parent, "full_name", None) == HA_CORE_REPO:
                    return True

            return False

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(f"Repository {owner}/{repo} not found") from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[str]:
        """
        Get list of file paths changed in a PR.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        try:
            files: list[str] = []
            page = 1
            per_page = 100

            while True:
                response = await self._client.generic(
                    endpoint=f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                    params={"per_page": per_page, "page": page},
                )
                data = response.data

                if not data:
                    break

                for file_data in data:
                    files.append(file_data.get("filename", ""))

                if len(data) < per_page:
                    break
                page += 1

            return files

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def file_exists(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> bool:
        """Check if a file exists in the repository."""
        try:
            params: dict[str, str] = {}
            if ref:
                params["ref"] = ref
            await self._client.repos.contents.get(
                f"{owner}/{repo}",
                path,
                **params,
            )
            return True
        except GitHubException:
            return False

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> str:
        """
        Get the content of a file.

        Raises:
            GitHubAPIError: If file not found or API error.

        """
        try:
            params: dict[str, str] = {}
            if ref:
                params["ref"] = ref
            response = await self._client.repos.contents.get(
                f"{owner}/{repo}",
                path,
                **params,
            )
            data = response.data

            # Handle single file (not directory)
            if hasattr(data, "content") and data.content:
                if data.encoding == "base64":
                    return base64.b64decode(data.content).decode("utf-8")
                return data.content

            raise GitHubAPIError(f"Path {path} is not a file or has no content")

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(f"File {path} not found in {owner}/{repo}") from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def download_archive(self, owner: str, repo: str, ref: str) -> bytes:
        """
        Download a repository archive as a tarball.

        Raises:
            GitHubAPIError: If download fails.

        """
        try:
            response = await self._client.repos.tarball(f"{owner}/{repo}", ref=ref)
            return response.data

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubException as err:
            raise GitHubAPIError(f"Failed to download archive: {err}") from err

    async def get_core_pr_integrations(
        self, owner: str, repo: str, pr_number: int
    ) -> list[str]:
        """Get list of integration domains modified in a core PR."""
        files = await self.get_pr_files(owner, repo, pr_number)
        integrations = set()

        for filename in files:
            # Check if file is in homeassistant/components/
            if filename.startswith(HA_CORE_COMPONENTS_PATH + "/"):
                # Extract integration name (first directory after components/)
                parts = filename[len(HA_CORE_COMPONENTS_PATH) + 1 :].split("/")
                if parts and parts[0]:
                    integrations.add(parts[0])

        return sorted(integrations)

    async def get_directory_contents(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> list[dict[str, str]]:
        """
        Get contents of a directory.

        Raises:
            GitHubAPIError: If directory not found or API error.

        """
        try:
            params: dict[str, str] = {}
            if ref:
                params["ref"] = ref
            response = await self._client.repos.contents.get(
                f"{owner}/{repo}",
                path,
                **params,
            )
            data = response.data

            # Handle directory listing
            if isinstance(data, list):
                return [{"name": item.name, "type": item.type} for item in data]

            raise GitHubAPIError(f"Path {path} is not a directory")

        except (GitHubAuthenticationException, GitHubPermissionException) as err:
            raise GitHubAuthError(f"GitHub authentication failed: {err}") from err
        except GitHubRatelimitException as err:
            raise GitHubRateLimitError("GitHub API rate limit exceeded") from err
        except GitHubNotFoundException as err:
            raise GitHubAPIError(
                f"Directory {path} not found in {owner}/{repo}"
            ) from err
        except GitHubException as err:
            raise GitHubAPIError(f"GitHub API error: {err}") from err

    async def resolve_reference(self, parsed_url: ParsedGitHubURL) -> ResolvedReference:
        """
        Resolve a parsed GitHub URL to get the commit SHA and type-specific info.

        Handles default branch resolution and fetches the appropriate
        reference info based on the URL type (PR, branch, or commit).

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAPIError: For other API errors.

        """
        owner = parsed_url.owner
        repo = parsed_url.repo
        ref_type = parsed_url.reference_type
        ref_value = parsed_url.reference_value

        # Check if this is home-assistant/core or a fork of it
        is_core = await self.is_core_or_fork(owner, repo)

        # Resolve default branch if needed
        if ref_type == ReferenceType.BRANCH and ref_value is None:
            ref_value = await self.get_default_branch(owner, repo)

        if ref_type == ReferenceType.PR:
            pr_info = await self.get_pr_info(owner, repo, int(ref_value))
            return ResolvedReference(
                owner=owner,
                repo=repo,
                reference_type=ref_type,
                reference_value=ref_value,
                is_core_or_fork_repo=is_core,
                commit_sha=pr_info.head_sha,
                pr_info=pr_info,
            )

        if ref_type == ReferenceType.BRANCH:
            branch_info = await self.get_branch_info(owner, repo, ref_value)
            return ResolvedReference(
                owner=owner,
                repo=repo,
                reference_type=ref_type,
                reference_value=ref_value,
                is_core_or_fork_repo=is_core,
                commit_sha=branch_info.head_sha,
                branch_info=branch_info,
            )

        # COMMIT
        commit_info = await self.get_commit_info(owner, repo, ref_value)
        return ResolvedReference(
            owner=owner,
            repo=repo,
            reference_type=ref_type,
            reference_value=ref_value,
            is_core_or_fork_repo=is_core,
            commit_sha=commit_info.sha,
            commit_info=commit_info,
        )
