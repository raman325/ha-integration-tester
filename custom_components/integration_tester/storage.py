"""Storage utilities for Integration Tester."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store

from .const import CONF_GITHUB_TOKEN, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.storage"


async def async_load_token(hass: HomeAssistant) -> str | None:
    """Load the GitHub token from storage."""
    store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load()
    if data is None:
        return None
    return data.get(CONF_GITHUB_TOKEN)


async def async_save_token(hass: HomeAssistant, token: str) -> None:
    """Save the GitHub token to storage."""
    store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    await store.async_save({CONF_GITHUB_TOKEN: token})
