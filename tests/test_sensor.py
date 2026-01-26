"""Tests for sensor entities."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass

from custom_components.integration_tester.const import (
    CONF_INSTALLED_COMMIT,
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DATA_BRANCH_NAME,
    DATA_BRANCH_URL,
    DATA_COMMIT_AUTHOR,
    DATA_COMMIT_DATE,
    DATA_COMMIT_HASH,
    DATA_COMMIT_MESSAGE,
    DATA_COMMIT_URL,
    DATA_INTEGRATION_DOMAIN,
    DATA_IS_PART_OF_HA_CORE,
    DATA_LAST_PUSH,
    DATA_PR_NUMBER,
    DATA_PR_STATE,
    DATA_PR_TITLE,
    DATA_PR_URL,
    DATA_REFERENCE_TYPE,
    DATA_REPO_URL,
    ReferenceType,
)
from custom_components.integration_tester.sensor import (
    CommitSensor,
    LastPushSensor,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        DATA_COMMIT_HASH: "abc123def456789",
        DATA_COMMIT_MESSAGE: "Test commit message",
        DATA_COMMIT_AUTHOR: "Test Author",
        DATA_COMMIT_DATE: "2024-01-15T10:30:00Z",
        DATA_COMMIT_URL: "https://github.com/owner/repo/commit/abc123def456789",
        DATA_LAST_PUSH: "2024-01-15T10:30:00Z",
        DATA_REPO_URL: "https://github.com/owner/repo",
        DATA_IS_PART_OF_HA_CORE: False,
        DATA_PR_NUMBER: 123,
        DATA_PR_URL: "https://github.com/owner/repo/pull/123",
        DATA_PR_TITLE: "Test PR Title",
        DATA_PR_STATE: "open",
    }
    coordinator.last_update_success = True
    return coordinator


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        CONF_URL: "https://github.com/owner/repo/pull/123",
        CONF_REFERENCE_TYPE: ReferenceType.PR.value,
        CONF_REFERENCE_VALUE: "123",
        CONF_INTEGRATION_DOMAIN: "test_domain",
        CONF_INSTALLED_COMMIT: "abc123",
    }
    return entry


class TestCommitSensor:
    """Tests for CommitSensor."""

    def test_native_value(self, mock_coordinator, mock_entry):
        """Test native value returns short commit hash."""
        sensor = CommitSensor(mock_coordinator, mock_entry)
        assert sensor.native_value == "abc123d"

    def test_native_value_no_data(self, mock_coordinator, mock_entry):
        """Test native value when no data."""
        mock_coordinator.data = None
        sensor = CommitSensor(mock_coordinator, mock_entry)
        assert sensor.native_value is None

    def test_extra_state_attributes_pr(self, mock_coordinator, mock_entry):
        """Test extra state attributes for PR reference."""
        sensor = CommitSensor(mock_coordinator, mock_entry)
        attrs = sensor.extra_state_attributes

        assert attrs[DATA_COMMIT_HASH] == "abc123def456789"
        assert attrs[DATA_COMMIT_MESSAGE] == "Test commit message"
        assert attrs[DATA_COMMIT_AUTHOR] == "Test Author"
        assert attrs[DATA_REFERENCE_TYPE] == "pr"
        assert attrs[DATA_INTEGRATION_DOMAIN] == "test_domain"
        assert attrs[DATA_PR_NUMBER] == 123
        assert attrs[DATA_PR_URL] == "https://github.com/owner/repo/pull/123"
        assert attrs[DATA_PR_TITLE] == "Test PR Title"

    def test_extra_state_attributes_branch(self, mock_coordinator, mock_entry):
        """Test extra state attributes for branch reference."""
        mock_entry.data[CONF_REFERENCE_TYPE] = ReferenceType.BRANCH.value
        mock_entry.data[CONF_REFERENCE_VALUE] = "main"
        mock_coordinator.data[DATA_BRANCH_NAME] = "main"
        mock_coordinator.data[DATA_BRANCH_URL] = "https://github.com/owner/repo/tree/main"

        sensor = CommitSensor(mock_coordinator, mock_entry)
        attrs = sensor.extra_state_attributes

        assert attrs[DATA_REFERENCE_TYPE] == "branch"
        assert attrs[DATA_BRANCH_NAME] == "main"
        assert attrs[DATA_BRANCH_URL] == "https://github.com/owner/repo/tree/main"
        assert DATA_PR_NUMBER not in attrs

    def test_available(self, mock_coordinator, mock_entry):
        """Test available property."""
        sensor = CommitSensor(mock_coordinator, mock_entry)
        assert sensor.available is True

        mock_coordinator.last_update_success = False
        assert sensor.available is False

    def test_extra_state_attributes_no_data(self, mock_coordinator, mock_entry):
        """Test extra state attributes returns empty dict when no data."""
        mock_coordinator.data = None
        sensor = CommitSensor(mock_coordinator, mock_entry)
        attrs = sensor.extra_state_attributes
        assert attrs == {}


class TestLastPushSensor:
    """Tests for LastPushSensor."""

    def test_native_value(self, mock_coordinator, mock_entry):
        """Test native value returns datetime."""
        sensor = LastPushSensor(mock_coordinator, mock_entry)
        value = sensor.native_value

        assert value is not None
        assert value.year == 2024
        assert value.month == 1
        assert value.day == 15

    def test_native_value_no_data(self, mock_coordinator, mock_entry):
        """Test native value when no data."""
        mock_coordinator.data = None
        sensor = LastPushSensor(mock_coordinator, mock_entry)
        assert sensor.native_value is None

    def test_native_value_invalid_date(self, mock_coordinator, mock_entry):
        """Test native value with invalid date string."""
        mock_coordinator.data[DATA_LAST_PUSH] = "not-a-date"
        sensor = LastPushSensor(mock_coordinator, mock_entry)
        assert sensor.native_value is None

    def test_device_class(self, mock_coordinator, mock_entry):
        """Test device class is timestamp."""
        sensor = LastPushSensor(mock_coordinator, mock_entry)
        assert sensor.device_class == SensorDeviceClass.TIMESTAMP
