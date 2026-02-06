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
    DATA_BRANCH_URL,
    DATA_COMMIT_AUTHOR,
    DATA_COMMIT_DATE,
    DATA_COMMIT_HASH,
    DATA_COMMIT_MESSAGE,
    DATA_COMMIT_URL,
    DATA_INTEGRATION_DOMAIN,
    DATA_IS_PART_OF_HA_CORE,
    DATA_LAST_PUSH,
    DATA_PR_AUTHOR,
    DATA_PR_NUMBER,
    DATA_PR_STATE,
    DATA_PR_TITLE,
    DATA_PR_URL,
    DATA_REFERENCE_TYPE,
    DATA_REPO_URL,
    DATA_SOURCE_BRANCH,
    DATA_SOURCE_REPO_URL,
    DATA_TARGET_BRANCH,
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
    coordinator: IntegrationTesterCoordinator = entry.runtime_data

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
        full_hash = self.coordinator.data.get(DATA_COMMIT_HASH, "")
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
            DATA_COMMIT_HASH: data.get(DATA_COMMIT_HASH, ""),
            DATA_COMMIT_URL: data.get(DATA_COMMIT_URL, ""),
            DATA_COMMIT_MESSAGE: data.get(DATA_COMMIT_MESSAGE, ""),
            DATA_COMMIT_AUTHOR: data.get(DATA_COMMIT_AUTHOR, ""),
            DATA_COMMIT_DATE: data.get(DATA_COMMIT_DATE, ""),
            DATA_REPO_URL: data.get(DATA_REPO_URL, ""),
            DATA_REFERENCE_TYPE: ref_type.value,
            DATA_INTEGRATION_DOMAIN: entry_data[CONF_INTEGRATION_DOMAIN],
            DATA_IS_PART_OF_HA_CORE: data.get(DATA_IS_PART_OF_HA_CORE, False),
        }

        # Add branch-specific attributes
        if ref_type == ReferenceType.BRANCH:
            attrs[DATA_BRANCH_NAME] = data.get(
                DATA_BRANCH_NAME, entry_data.get(CONF_REFERENCE_VALUE, "")
            )
            attrs[DATA_BRANCH_URL] = data.get(DATA_BRANCH_URL, "")

        # Add PR-specific attributes
        if ref_type == ReferenceType.PR:
            attrs.update(
                {
                    DATA_PR_NUMBER: data.get(
                        DATA_PR_NUMBER, entry_data.get(CONF_REFERENCE_VALUE)
                    ),
                    DATA_PR_URL: data.get(DATA_PR_URL, ""),
                    DATA_PR_TITLE: data.get(DATA_PR_TITLE, ""),
                    DATA_PR_AUTHOR: data.get(DATA_PR_AUTHOR, ""),
                    DATA_PR_STATE: data.get(DATA_PR_STATE, ""),
                    DATA_SOURCE_REPO_URL: data.get(DATA_SOURCE_REPO_URL, ""),
                    DATA_SOURCE_BRANCH: data.get(DATA_SOURCE_BRANCH, ""),
                    DATA_TARGET_BRANCH: data.get(DATA_TARGET_BRANCH, ""),
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
