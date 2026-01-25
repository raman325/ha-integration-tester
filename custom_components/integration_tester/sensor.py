"""Sensor platform for Integration Tester."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_INTEGRATION_DOMAIN,
    CONF_REFERENCE_TYPE,
    CONF_REFERENCE_VALUE,
    DATA_BRANCH_NAME,
    DATA_COMMIT_AUTHOR,
    DATA_COMMIT_DATE,
    DATA_COMMIT_MESSAGE,
    DATA_COMMIT_URL,
    DATA_CURRENT_COMMIT,
    DATA_IS_CORE_OR_FORK,
    DATA_LAST_PUSH,
    DATA_PR_AUTHOR,
    DATA_PR_NUMBER,
    DATA_PR_STATE,
    DATA_PR_TITLE,
    DATA_PR_URL,
    DATA_REPO_URL,
    DATA_SOURCE_BRANCH,
    DATA_SOURCE_REPO_URL,
    DATA_TARGET_BRANCH,
    DOMAIN,
    ReferenceType,
)
from .coordinator import IntegrationTesterCoordinator

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: IntegrationTesterCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        CommitSensor(coordinator, entry),
        LastPushSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class IntegrationTesterSensorBase(
    CoordinatorEntity[IntegrationTesterCoordinator], SensorEntity
):
    """Base class for Integration Tester sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IntegrationTesterCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._domain = entry.data[CONF_INTEGRATION_DOMAIN]

        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )


class CommitSensor(IntegrationTesterSensorBase):
    """Sensor showing the current commit hash."""

    def __init__(
        self,
        coordinator: IntegrationTesterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the commit sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="commit",
                translation_key="commit",
                icon="mdi:source-commit",
            ),
        )

    @property
    def native_value(self) -> str | None:
        """Return the short commit hash."""
        if not self.coordinator.data:
            return None
        full_hash = self.coordinator.data.get(DATA_CURRENT_COMMIT, "")
        return full_hash[:7] if full_hash else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        entry_data = self._entry.data
        ref_type = ReferenceType(entry_data[CONF_REFERENCE_TYPE])

        attrs: dict[str, Any] = {
            "full_commit_hash": data.get(DATA_CURRENT_COMMIT, ""),
            "commit_url": data.get(DATA_COMMIT_URL, ""),
            "commit_message": data.get(DATA_COMMIT_MESSAGE, ""),
            "commit_author": data.get(DATA_COMMIT_AUTHOR, ""),
            "commit_date": data.get(DATA_COMMIT_DATE, ""),
            "repo_url": data.get(DATA_REPO_URL, ""),
            "reference_type": ref_type.value,
            "integration_domain": entry_data[CONF_INTEGRATION_DOMAIN],
            "is_core_integration": data.get(DATA_IS_CORE_OR_FORK, False),
        }

        # Add branch-specific attributes
        if ref_type == ReferenceType.BRANCH:
            attrs["branch_name"] = data.get(
                DATA_BRANCH_NAME, entry_data.get(CONF_REFERENCE_VALUE, "")
            )

        # Add PR-specific attributes
        if ref_type == ReferenceType.PR:
            attrs.update(
                {
                    "pr_number": data.get(
                        DATA_PR_NUMBER, entry_data.get(CONF_REFERENCE_VALUE)
                    ),
                    "pr_url": data.get(DATA_PR_URL, ""),
                    "pr_title": data.get(DATA_PR_TITLE, ""),
                    "pr_author": data.get(DATA_PR_AUTHOR, ""),
                    "pr_state": data.get(DATA_PR_STATE, ""),
                    "source_repo_url": data.get(DATA_SOURCE_REPO_URL, ""),
                    "source_branch": data.get(DATA_SOURCE_BRANCH, ""),
                    "target_branch": data.get(DATA_TARGET_BRANCH, ""),
                }
            )

        return attrs


class LastPushSensor(IntegrationTesterSensorBase):
    """Sensor showing the last push timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: IntegrationTesterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the last push sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="last_push",
                translation_key="last_push",
                icon="mdi:clock-outline",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the last push timestamp."""
        if not self.coordinator.data:
            return None
        date_str = self.coordinator.data.get(DATA_LAST_PUSH, "")
        if not date_str:
            return None
        try:
            # Parse ISO format datetime
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
