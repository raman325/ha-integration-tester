"""Tests for Integration Tester services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.integration_tester.const import (
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    CONF_URL,
    DOMAIN,
    ReferenceType,
)
from custom_components.integration_tester.services import (
    ATTR_DELETE_FILES,
    ATTR_DOMAIN,
    ATTR_ENTRY_ID,
    ATTR_OVERWRITE,
    ATTR_RESTART,
    ATTR_URL,
    SERVICE_ADD,
    SERVICE_LIST,
    SERVICE_REMOVE,
    SERVICE_REMOVE_SCHEMA,
    _find_entry_by_criteria,
    _get_integration_tester_entries,
    async_handle_add,
    async_handle_list,
    async_handle_remove,
    async_register_services,
    async_unregister_services,
)

from .conftest import create_config_entry


@pytest.fixture
def mock_entry_1(hass: HomeAssistant):
    """Create first mock config entry."""
    entry = create_config_entry(
        hass,
        domain=DOMAIN,
        title="Test 1 (PR #1)",
        data={
            CONF_URL: "https://github.com/owner1/repo1",
            CONF_REFERENCE_TYPE: ReferenceType.PR.value,
            CONF_REFERENCE_VALUE: "1",
            CONF_INTEGRATION_DOMAIN: "test_domain_1",
        },
        unique_id="test_domain_1",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_entry_2(hass: HomeAssistant):
    """Create second mock config entry."""
    entry = create_config_entry(
        hass,
        domain=DOMAIN,
        title="Test 2 (branch: main)",
        data={
            CONF_URL: "https://github.com/owner2/repo2",
            CONF_REFERENCE_TYPE: ReferenceType.BRANCH.value,
            CONF_REFERENCE_VALUE: "main",
            CONF_INTEGRATION_DOMAIN: "test_domain_2",
        },
        unique_id="test_domain_2",
    )
    entry.add_to_hass(hass)
    return entry


class TestGetIntegrationTesterEntries:
    """Tests for _get_integration_tester_entries."""

    def test_returns_entries(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test returns all Integration Tester entries."""
        entries = _get_integration_tester_entries(hass)
        assert len(entries) == 2

    def test_returns_empty_when_no_entries(self, hass: HomeAssistant):
        """Test returns empty list when no entries."""
        entries = _get_integration_tester_entries(hass)
        assert entries == []


class TestFindEntryByCriteria:
    """Tests for _find_entry_by_criteria."""

    def test_find_by_entry_id(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test finding entry by entry_id."""
        entry = _find_entry_by_criteria(hass, entry_id=mock_entry_1.entry_id)
        assert entry == mock_entry_1

    def test_find_by_domain(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test finding entry by domain."""
        entry = _find_entry_by_criteria(hass, domain="test_domain_2")
        assert entry == mock_entry_2

    def test_find_by_url(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test finding entry by URL matching on owner/repo."""
        # URL with same owner/repo matches when no specific ref required
        entry = _find_entry_by_criteria(
            hass, url="https://github.com/owner1/repo1/pull/1"
        )
        assert entry == mock_entry_1

    def test_find_by_url_branch(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test finding entry by URL with branch reference."""
        # URL with branch reference matches entry with same branch
        entry = _find_entry_by_criteria(
            hass, url="https://github.com/owner2/repo2/tree/main"
        )
        assert entry == mock_entry_2

    def test_find_by_owner_repo(self, hass: HomeAssistant, mock_entry_1, mock_entry_2):
        """Test finding entry by owner/repo."""
        entry = _find_entry_by_criteria(hass, owner_repo="owner2/repo2")
        assert entry == mock_entry_2

    def test_multiple_criteria_still_works(
        self, hass: HomeAssistant, mock_entry_1, mock_entry_2
    ):
        """Test function handles multiple criteria (though schema prevents this)."""
        # The function still works with multiple criteria for backwards compat
        # but the schema now prevents multiple via vol.Exclusive
        entry = _find_entry_by_criteria(
            hass,
            entry_id=mock_entry_1.entry_id,
            domain="test_domain_2",  # entry_id checked first
        )
        assert entry == mock_entry_1

    def test_not_found(self, hass: HomeAssistant, mock_entry_1):
        """Test returns None when not found."""
        entry = _find_entry_by_criteria(hass, domain="nonexistent")
        assert entry is None

    def test_no_criteria(self, hass: HomeAssistant, mock_entry_1):
        """Test returns None when no criteria provided."""
        entry = _find_entry_by_criteria(hass)
        assert entry is None


class TestAsyncHandleAdd:
    """Tests for async_handle_add."""

    @pytest.mark.asyncio
    async def test_add_success(self, hass: HomeAssistant):
        """Test successful add creates config entry."""
        call = MagicMock()
        call.data = {
            ATTR_URL: "https://github.com/owner/repo/pull/123",
            ATTR_OVERWRITE: False,
            ATTR_RESTART: False,
        }

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as mock_init:
            mock_init.return_value = {"type": "create_entry", "entry_id": "test_id"}
            await async_handle_add(hass, call)

        mock_init.assert_called_once_with(
            DOMAIN,
            context={"source": "import"},
            data={
                "url": "https://github.com/owner/repo/pull/123",
                "overwrite": False,
                "restart": False,
            },
        )

    @pytest.mark.asyncio
    async def test_add_abort_raises_error(self, hass: HomeAssistant):
        """Test add raises error when flow aborts."""
        call = MagicMock()
        call.data = {
            ATTR_URL: "https://github.com/owner/repo/pull/123",
            ATTR_OVERWRITE: False,
            ATTR_RESTART: False,
        }

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as mock_init:
            mock_init.return_value = {"type": "abort", "reason": "already_configured"}
            with pytest.raises(HomeAssistantError, match="already_configured"):
                await async_handle_add(hass, call)

    @pytest.mark.asyncio
    async def test_add_form_with_errors(self, hass: HomeAssistant):
        """Test add raises error when flow shows form with errors."""
        call = MagicMock()
        call.data = {
            ATTR_URL: "https://github.com/owner/repo/pull/123",
            ATTR_OVERWRITE: False,
            ATTR_RESTART: False,
        }

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as mock_init:
            mock_init.return_value = {
                "type": "form",
                "errors": {"url": "invalid_url"},
            }
            with pytest.raises(HomeAssistantError, match="invalid_url"):
                await async_handle_add(hass, call)

    @pytest.mark.asyncio
    async def test_add_form_requires_interaction(self, hass: HomeAssistant):
        """Test add raises error when flow requires user interaction."""
        call = MagicMock()
        call.data = {
            ATTR_URL: "https://github.com/owner/repo/pull/123",
            ATTR_OVERWRITE: False,
            ATTR_RESTART: False,
        }

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as mock_init:
            mock_init.return_value = {"type": "form", "errors": {}}
            with pytest.raises(HomeAssistantError, match="requires additional"):
                await async_handle_add(hass, call)


class TestAsyncHandleList:
    """Tests for async_handle_list."""

    @pytest.mark.asyncio
    async def test_list_empty(self, hass: HomeAssistant):
        """Test list returns empty when no entries."""
        call = MagicMock()
        result = await async_handle_list(hass, call)
        assert result == {"entries": [], "count": 0}

    @pytest.mark.asyncio
    async def test_list_with_entries(
        self, hass: HomeAssistant, mock_entry_1, mock_entry_2
    ):
        """Test list returns all entries."""
        call = MagicMock()
        result = await async_handle_list(hass, call)

        assert result["count"] == 2
        assert len(result["entries"]) == 2

        # Check first entry
        entry_1 = next(e for e in result["entries"] if e["domain"] == "test_domain_1")
        assert entry_1["entry_id"] == mock_entry_1.entry_id
        assert entry_1["owner_repo"] == "owner1/repo1"
        assert entry_1["reference_type"] == "pr"
        assert entry_1["reference_value"] == "1"


class TestAsyncHandleRemove:
    """Tests for async_handle_remove."""

    @pytest.mark.asyncio
    async def test_remove_by_domain(self, hass: HomeAssistant, mock_entry_1):
        """Test delete by domain."""
        call = MagicMock()
        call.data = {ATTR_DOMAIN: "test_domain_1", ATTR_DELETE_FILES: True}

        with patch.object(
            hass.config_entries, "async_remove", new_callable=AsyncMock
        ) as mock_remove:
            await async_handle_remove(hass, call)

        mock_remove.assert_called_once_with(mock_entry_1.entry_id)

    @pytest.mark.asyncio
    async def test_remove_by_entry_id(self, hass: HomeAssistant, mock_entry_1):
        """Test delete by entry_id."""
        call = MagicMock()
        call.data = {ATTR_ENTRY_ID: mock_entry_1.entry_id, ATTR_DELETE_FILES: True}

        with patch.object(
            hass.config_entries, "async_remove", new_callable=AsyncMock
        ) as mock_remove:
            await async_handle_remove(hass, call)

        mock_remove.assert_called_once_with(mock_entry_1.entry_id)

    def test_remove_schema_requires_one_key(self):
        """Test delete schema requires at least one identifier."""
        with pytest.raises(vol.MultipleInvalid, match="must contain at least one"):
            SERVICE_REMOVE_SCHEMA({})

    def test_remove_schema_rejects_multiple_keys(self):
        """Test delete schema rejects multiple identifiers."""
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_REMOVE_SCHEMA({"domain": "test", "entry_id": "123"})

    @pytest.mark.asyncio
    async def test_remove_not_found_raises_error(
        self, hass: HomeAssistant, mock_entry_1
    ):
        """Test delete raises error when entry not found."""
        call = MagicMock()
        call.data = {ATTR_DOMAIN: "nonexistent", ATTR_DELETE_FILES: True}

        with pytest.raises(HomeAssistantError, match="No matching"):
            await async_handle_remove(hass, call)


class TestServiceRegistration:
    """Tests for service registration and unregistration."""

    def test_register_services(self, hass: HomeAssistant):
        """Test services are registered."""
        async_register_services(hass)

        assert hass.services.has_service(DOMAIN, SERVICE_ADD)
        assert hass.services.has_service(DOMAIN, SERVICE_LIST)
        assert hass.services.has_service(DOMAIN, SERVICE_REMOVE)

    def test_unregister_services(self, hass: HomeAssistant):
        """Test services are unregistered."""
        async_register_services(hass)
        async_unregister_services(hass)

        assert not hass.services.has_service(DOMAIN, SERVICE_ADD)
        assert not hass.services.has_service(DOMAIN, SERVICE_LIST)
        assert not hass.services.has_service(DOMAIN, SERVICE_REMOVE)


class TestFindEntryByCriteriaEdgeCases:
    """Additional edge case tests for _find_entry_by_criteria."""

    def test_find_by_entry_id_not_found(
        self, hass: HomeAssistant, mock_entry_1, mock_entry_2
    ):
        """Test returns None when entry_id not found."""
        entry = _find_entry_by_criteria(hass, entry_id="nonexistent_id")
        assert entry is None

    def test_find_by_url_invalid_url(self, hass: HomeAssistant, mock_entry_1):
        """Test returns None when URL is invalid."""
        entry = _find_entry_by_criteria(hass, url="not-a-valid-url")
        assert entry is None

    def test_find_by_url_owner_repo_only(self, hass: HomeAssistant, mock_entry_1):
        """Test finding entry by URL with just owner/repo (no ref)."""
        # Create a PR URL without specific ref matching
        entry = _find_entry_by_criteria(hass, url="https://github.com/owner1/repo1")
        assert entry == mock_entry_1

    def test_find_by_url_skips_invalid_entries(self, hass: HomeAssistant):
        """Test URL search skips entries with invalid URLs."""
        # Create entry with invalid URL
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Invalid",
            data={
                CONF_URL: "invalid-url",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "test_invalid",
            },
            unique_id="test_invalid",
        )
        entry.add_to_hass(hass)

        # Should return None, not crash
        result = _find_entry_by_criteria(
            hass, url="https://github.com/owner/repo/pull/1"
        )
        assert result is None

    def test_find_by_owner_repo_skips_invalid_entries(self, hass: HomeAssistant):
        """Test owner_repo search skips entries with invalid URLs."""
        # Create entry with invalid URL
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Invalid",
            data={
                CONF_URL: "invalid-url",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "test_invalid",
            },
            unique_id="test_invalid",
        )
        entry.add_to_hass(hass)

        # Should return None, not crash
        result = _find_entry_by_criteria(hass, owner_repo="owner/repo")
        assert result is None


class TestAsyncHandleListEdgeCases:
    """Edge case tests for async_handle_list."""

    @pytest.mark.asyncio
    async def test_list_with_invalid_url_in_entry(self, hass: HomeAssistant):
        """Test list handles entries with invalid URLs gracefully."""
        # Create entry with invalid URL
        entry = create_config_entry(
            hass,
            domain=DOMAIN,
            title="Invalid URL Entry",
            data={
                CONF_URL: "not-a-github-url",
                CONF_REFERENCE_TYPE: ReferenceType.PR.value,
                CONF_REFERENCE_VALUE: "1",
                CONF_INTEGRATION_DOMAIN: "test_invalid",
            },
            unique_id="test_invalid",
        )
        entry.add_to_hass(hass)

        call = MagicMock()
        call.data = {}

        result = await async_handle_list(hass, call)

        assert result["count"] == 1
        assert result["entries"][0]["owner_repo"] == "unknown"
        assert result["entries"][0]["domain"] == "test_invalid"
