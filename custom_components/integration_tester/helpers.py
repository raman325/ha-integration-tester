"""Helper utilities for Integration Tester."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import re
import shutil
import tarfile
from typing import TYPE_CHECKING

from .api import IntegrationTesterGitHubAPI
from .const import HA_CORE_COMPONENTS_PATH, HA_CORE_REPO, MARKER_FILE, ReferenceType
from .exceptions import (
    GitHubAPIError,
    IntegrationNotFoundError,
    InvalidGitHubURLError,
    ManifestNotFoundError,
)
from .models import IntegrationInfo, ParsedGitHubURL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# URL patterns for parsing GitHub URLs
GITHUB_URL_PATTERNS = [
    # PR: github.com/owner/repo/pull/123
    re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
        r"/pull/(?P<pr_number>\d+)/?$"
    ),
    # Commit: github.com/owner/repo/commit/abc123
    re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
        r"/commit/(?P<commit>[a-fA-F0-9]+)/?$"
    ),
    # Branch: github.com/owner/repo/tree/branch-name
    re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
        r"/tree/(?P<branch>.+?)/?$"
    ),
    # Default branch: github.com/owner/repo
    re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/?$"
    ),
]


def parse_github_url(url: str) -> ParsedGitHubURL:
    """
    Parse a GitHub URL and extract repository information.

    Raises:
        InvalidGitHubURLError: If the URL is not a valid GitHub URL.

    """
    for pattern in GITHUB_URL_PATTERNS:
        match = pattern.match(url.strip())
        if match:
            groups = match.groupdict()
            owner = groups["owner"]
            repo = groups["repo"]
            is_core = f"{owner}/{repo}" == HA_CORE_REPO

            if "pr_number" in groups:
                return ParsedGitHubURL(
                    owner=owner,
                    repo=repo,
                    reference_type=ReferenceType.PR,
                    reference_value=groups["pr_number"],
                    is_part_of_ha_core=is_core,
                )
            if "commit" in groups:
                return ParsedGitHubURL(
                    owner=owner,
                    repo=repo,
                    reference_type=ReferenceType.COMMIT,
                    reference_value=groups["commit"],
                    is_part_of_ha_core=is_core,
                )
            if "branch" in groups:
                return ParsedGitHubURL(
                    owner=owner,
                    repo=repo,
                    reference_type=ReferenceType.BRANCH,
                    reference_value=groups["branch"],
                    is_part_of_ha_core=is_core,
                )
            # Default branch
            return ParsedGitHubURL(
                owner=owner,
                repo=repo,
                reference_type=ReferenceType.BRANCH,
                reference_value=None,  # Will be resolved to default branch
                is_part_of_ha_core=is_core,
            )

    raise InvalidGitHubURLError(f"Invalid GitHub URL: {url}")


async def validate_custom_integration(
    api: IntegrationTesterGitHubAPI, owner: str, repo: str, ref: str | None = None
) -> IntegrationInfo:
    """
    Validate that a repository contains a custom integration.

    Raises:
        ManifestNotFoundError: If manifest.json is not found.

    """
    # Get repository contents to find the integration
    try:
        contents = await api.get_directory_contents(
            owner, repo, "custom_components", ref
        )

        # Find the integration directory
        for item in contents:
            if item.get("type") == "dir":
                domain = item["name"]
                manifest_path = f"custom_components/{domain}/manifest.json"
                try:
                    manifest_content = await api.get_file_content(
                        owner, repo, manifest_path, ref
                    )
                    manifest = json.loads(manifest_content)
                    return IntegrationInfo(
                        domain=manifest.get("domain", domain),
                        name=manifest.get("name", domain),
                        is_part_of_ha_core=False,
                    )
                except (GitHubAPIError, json.JSONDecodeError):
                    continue

    except GitHubAPIError:
        pass

    raise ManifestNotFoundError(
        f"Could not find manifest.json in {owner}/{repo}. "
        "Expected structure: custom_components/<domain>/manifest.json"
    )


async def get_core_integration_info(
    api: IntegrationTesterGitHubAPI,
    owner: str,
    repo: str,
    domain: str,
    ref: str | None = None,
) -> IntegrationInfo:
    """
    Get integration info from HA core repository.

    Raises:
        IntegrationNotFoundError: If integration not found.

    """
    manifest_path = f"{HA_CORE_COMPONENTS_PATH}/{domain}/manifest.json"
    try:
        manifest_content = await api.get_file_content(owner, repo, manifest_path, ref)
        manifest = json.loads(manifest_content)
        return IntegrationInfo(
            domain=manifest.get("domain", domain),
            name=manifest.get("name", domain),
            is_part_of_ha_core=True,
        )
    except (GitHubAPIError, json.JSONDecodeError) as err:
        raise IntegrationNotFoundError(
            f"Integration {domain} not found in {owner}/{repo}"
        ) from err


def extract_integration(
    config_dir: Path,
    archive_data: bytes,
    domain: str,
    is_part_of_ha_core: bool,
) -> Path:
    """
    Extract integration files from archive to custom_components.

    This is a sync function that performs blocking I/O. Callers should run it
    in an executor via hass.async_add_executor_job().

    """
    target_dir = config_dir / "custom_components" / domain

    # Ensure custom_components exists
    custom_components_dir = config_dir / "custom_components"
    custom_components_dir.mkdir(exist_ok=True)

    # Remove existing directory if it exists
    if target_dir.exists():
        shutil.rmtree(target_dir)

    with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as tf:
        # Find the root directory in the archive
        members = tf.getmembers()
        if not members:
            raise ValueError("Empty archive")

        # GitHub archives have a root directory like "repo-branch/"
        root_dir = members[0].name.split("/")[0]

        if is_part_of_ha_core:
            # For core integrations, extract from homeassistant/components/domain/
            source_prefix = f"{root_dir}/{HA_CORE_COMPONENTS_PATH}/{domain}/"
        else:
            # For custom integrations, extract from custom_components/domain/
            source_prefix = f"{root_dir}/custom_components/{domain}/"

        # Create target directory
        target_dir.mkdir(parents=True, exist_ok=True)

        # Extract matching files
        for member in members:
            if member.name.startswith(source_prefix) and member.isfile():
                # Calculate relative path within the integration
                relative_path = member.name[len(source_prefix) :]
                if relative_path:
                    target_path = target_dir / relative_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    # Extract file
                    with tf.extractfile(member) as src:
                        if src:
                            with open(target_path, "wb") as dst:
                                dst.write(src.read())

        # Write marker file
        marker_path = target_dir / MARKER_FILE
        marker_path.touch()

        return target_dir


def integration_has_marker(hass: HomeAssistant, domain: str) -> bool:
    """Check if an integration directory has our marker file."""
    config_dir = Path(hass.config.config_dir)
    marker_path = config_dir / "custom_components" / domain / MARKER_FILE
    return marker_path.exists()


def integration_exists(hass: HomeAssistant, domain: str) -> bool:
    """Check if an integration directory exists."""
    config_dir = Path(hass.config.config_dir)
    integration_dir = config_dir / "custom_components" / domain
    return integration_dir.is_dir()


async def remove_integration(hass: HomeAssistant, domain: str) -> None:
    """Remove an integration directory."""
    config_dir = Path(hass.config.config_dir)
    integration_dir = config_dir / "custom_components" / domain

    if integration_dir.exists():
        await hass.async_add_executor_job(shutil.rmtree, integration_dir)
