"""Fixtures for integration_tester tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

pytest_plugins = ["pytest_homeassistant_custom_component"]


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


def load_fixture(filename: str) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a fixture file."""
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


@pytest.fixture
def pr_response() -> dict[str, Any]:
    """Load PR response fixture."""
    return load_fixture("pr_response.json")


@pytest.fixture
def commit_response() -> dict[str, Any]:
    """Load commit response fixture."""
    return load_fixture("commit_response.json")


@pytest.fixture
def branch_response() -> dict[str, Any]:
    """Load branch response fixture."""
    return load_fixture("branch_response.json")


@pytest.fixture
def core_pr_response() -> dict[str, Any]:
    """Load core PR response fixture."""
    return load_fixture("core_pr_response.json")


@pytest.fixture
def core_pr_files_response() -> list[dict[str, Any]]:
    """Load core PR files response fixture."""
    return load_fixture("core_pr_files_response.json")


@pytest.fixture
def manifest_json_contents() -> dict[str, Any]:
    """Load manifest.json contents fixture."""
    return load_fixture("manifest_json_contents.json")


def create_tarball(files: dict[str, str]) -> bytes:
    """Create a tarball from a dict of path -> content.

    Args:
        files: Dict mapping archive path to file content.

    Returns:
        Tarball content as bytes.

    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def mock_archive_data() -> bytes:
    """Create mock tarball archive data."""
    return create_tarball(
        {
            "test-repo-main/custom_components/test_integration/__init__.py": "# Test integration",
            "test-repo-main/custom_components/test_integration/manifest.json": json.dumps(
                {
                    "domain": "test_integration",
                    "name": "Test Integration",
                    "version": "1.0.0",
                }
            ),
            "test-repo-main/hacs.json": json.dumps({"name": "Test Integration"}),
        }
    )


@pytest.fixture
def mock_core_archive_data() -> bytes:
    """Create mock tarball archive data for core integration."""
    return create_tarball(
        {
            "core-dev/homeassistant/components/test_domain/__init__.py": "# Test core integration",
            "core-dev/homeassistant/components/test_domain/manifest.json": json.dumps(
                {
                    "domain": "test_domain",
                    "name": "Test Domain",
                    "version": "1.0.0",
                }
            ),
        }
    )


@pytest.fixture
def mock_custom_components_dir(hass: HomeAssistant, tmp_path: Path):
    """Mock custom_components directory."""
    custom_components = tmp_path / "custom_components"
    custom_components.mkdir()

    with patch.object(hass.config, "config_dir", str(tmp_path)):
        yield custom_components


def create_mock_response(data: Any, status_code: int = 200) -> MagicMock:
    """Create a mock aiogithubapi response.

    Args:
        data: The data to return (aiogithubapi uses .data attribute).
        status_code: HTTP status code.

    Returns:
        MagicMock response object.

    """
    response = MagicMock()
    response.data = data
    response.status_code = status_code
    return response


def dict_to_object(data: dict[str, Any]) -> MagicMock:
    """Convert a dict to a mock object with attributes.

    This recursively converts nested dicts to objects.

    Args:
        data: Dict to convert.

    Returns:
        MagicMock object with attributes.

    """
    obj = MagicMock()
    for key, value in data.items():
        if isinstance(value, dict):
            setattr(obj, key, dict_to_object(value))
        elif isinstance(value, list):
            setattr(
                obj,
                key,
                [
                    dict_to_object(item) if isinstance(item, dict) else item
                    for item in value
                ],
            )
        else:
            setattr(obj, key, value)
    return obj


@pytest.fixture
def mock_github_client():
    """Create a mock GitHub client for testing.

    Yields a mock that can be configured with specific responses.
    """
    with patch("custom_components.integration_tester.api.GitHubAPI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        # Set up the namespace structure for aiogithubapi
        mock_client.repos = MagicMock()
        mock_client.repos.contents = MagicMock()
        mock_client.repos.pulls = MagicMock()
        mock_client.generic = MagicMock()

        yield mock_client


def create_config_entry(
    hass: HomeAssistant,
    *,
    version: int = 1,
    minor_version: int = 1,
    domain: str,
    title: str,
    data: dict[str, Any],
    source: str = "user",
    unique_id: str | None = None,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Create a MockConfigEntry for testing.

    Args:
        hass: Home Assistant instance (unused but kept for API compatibility).
        version: Entry version.
        minor_version: Entry minor version.
        domain: Integration domain.
        title: Entry title.
        data: Entry data.
        source: Entry source.
        unique_id: Entry unique ID.
        options: Entry options.

    Returns:
        MockConfigEntry instance.

    """
    return MockConfigEntry(
        version=version,
        minor_version=minor_version,
        domain=domain,
        title=title,
        data=data,
        source=source,
        unique_id=unique_id,
        options=options or {},
    )
