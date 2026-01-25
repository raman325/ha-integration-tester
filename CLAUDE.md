# CLAUDE.md

## Project Overview

Integration Tester is a Home Assistant custom integration that downloads and installs
custom integrations from GitHub URLs. It supports:

- External HACS-compatible repos (branches, PRs, commits)
- Home Assistant core repo (extracts single integrations from PRs/branches/commits)

## Development Commands

```bash
# Install dependencies
uv pip install -r requirements_dev.txt

# Run tests
pytest tests/

# Run tests with coverage
pytest tests/ --cov=custom_components/integration_tester/ --cov-report=html

# Run linting
ruff check .
ruff format --check .

# Run pre-commit hooks
pre-commit run --all-files
```

## Code Style

- Follow Home Assistant integration patterns
- Use `from homeassistant.x import Y` style imports (canonical top-level modules)
- GitHub API calls use `aiogithubapi` SDK with HA's shared aiohttp session via `async_get_clientsession(hass)`
- Use `hass.async_add_executor_job()` for running sync functions in async context
- Tests should use fixtures from real GitHub API responses (stored in tests/fixtures/)

## Key Design Decisions

- Unique ID is `integration_domain` (one active installation per domain)
- Marker file `.integration_tester` tracks which folders we manage
- Commits are pinned (no update entity), branches/PRs have update entities
- Hourly polling for updates, manual trigger via update entity
- Repair issues used for: restart required, PR merged/closed, integration removed from diff

## Testing

- Target 100% code coverage
- Use real GitHub API response fixtures (tests/fixtures/)
- Mock `aiogithubapi.GitHub` client to return fixture data converted via `dict_to_object()`
- Use built-in mocks from pytest-homeassistant-custom-component wherever possible
- pytest with pytest-homeassistant-custom-component
