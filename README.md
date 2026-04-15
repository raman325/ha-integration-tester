# Integration Tester

[![GitHub Release][releases-shield]][releases]
[![HACS][hacsbadge]][hacs]
[![License][license-shield]][license]

Download and install Home Assistant integrations from GitHub URLs. Test PRs, branches, or specific commits of both:

- **External repositories** (custom integrations)
- **Home Assistant core PRs** (to override built-in integrations)

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Integration Tester" and install
3. Restart Home Assistant

### Manual

1. Copy `custom_components/integration_tester` to your `custom_components` folder
2. Restart Home Assistant

## Usage

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for "Integration Tester"
3. Enter a GitHub URL in one of these formats:

| Format | Example |
|--------|---------|
| Default branch | `github.com/owner/repo` |
| Specific branch | `github.com/owner/repo/tree/branch-name` |
| Pull request | `github.com/owner/repo/pull/123` |
| Specific commit | `github.com/owner/repo/commit/abc123` |

### For Custom Integrations

The repository must follow the standard custom integration structure with a `manifest.json`. The integration will:

1. Find the `manifest.json` to determine the integration domain
2. Download and install to `custom_components/<domain>`
3. Create a repair issue prompting you to restart

### For Home Assistant Core PRs

Use a PR URL like `github.com/home-assistant/core/pull/12345` (or from your own fork of core):

1. The integration will analyze which integrations the PR modifies
2. If multiple, you'll select which one to install
3. The integration is extracted and installed as a custom component, overriding the built-in version

## Configuration Options

### Config Flow (UI)

| Field | Description |
|-------|-------------|
| **URL** | GitHub URL (PR, branch, commit, or plain owner/repo) |
| **GitHub Token** | Personal access token (only shown if not already configured) |
| **Restart after install** | Automatically restart HA after the integration is installed |

### Options Flow

The GitHub token can be updated at any time via any Integration Tester
config entry's options flow
(Settings > Devices & Services > Integration Tester > Configure).

## Services

### `integration_tester.add`

Install an integration from a GitHub URL.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `url` | Yes | — | GitHub URL (PR, branch, commit, or plain owner/repo) |
| `domain` | No | — | Integration domain to install. Only needed for core PRs that modify multiple integrations. |
| `overwrite` | No | `false` | Replace an existing Integration Tester entry or overwrite an unmanaged `custom_components/` folder for the same domain |
| `restart` | No | `false` | Automatically restart HA after install |

```yaml
service: integration_tester.add
data:
  url: "https://github.com/owner/repo/pull/123"
  overwrite: true
  restart: true
```

### `integration_tester.list`

Returns all integrations managed by Integration Tester. This is a
response-only service (use in Developer Tools > Services with
"Return response" enabled, or in automations with `response_variable`).

```yaml
service: integration_tester.list
```

Response:

```json
{
  "entries": [
    {
      "entry_id": "...",
      "domain": "my_integration",
      "url": "https://github.com/owner/repo",
      "owner_repo": "owner/repo",
      "reference_type": "pr",
      "reference_value": "123",
      "title": "My Integration (PR #123)"
    }
  ],
  "count": 1
}
```

### `integration_tester.remove`

Remove a managed integration. Provide exactly one identifier.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `domain` | One of these | — | Integration domain (e.g., `my_integration`) |
| `url` | One of these | — | GitHub URL to match |
| `owner_repo` | One of these | — | Owner/repo slug (e.g., `owner/repo`) |
| `entry_id` | One of these | — | Config entry ID |
| `delete_files` | No | `true` | Delete integration files from `custom_components/`. Set to `false` to remove the config entry but keep the files in place. |

```yaml
service: integration_tester.remove
data:
  domain: "my_integration"
  delete_files: false
```

## Features

### Entities

Each tracked integration creates a device with the following entities:

| Entity | Description |
|--------|-------------|
| **Commit** (sensor) | Current commit hash with attributes for full hash, message, author, date, repo URL, and reference-specific metadata (PR number/state/title, branch name, etc.) |
| **Last Push** (sensor) | Timestamp of the last push to the tracked branch/PR |
| **Update** (update) | Available for PRs and branches only. Checks every 5 minutes for new commits and allows one-click install from the UI. |

### Repair Issues

| Issue | Severity | Description |
|-------|----------|-------------|
| **Restart required** | Warning | After installing or updating. Click "Fix" to restart HA. |
| **PR merged/closed** | Error | When a tracked PR is no longer open. Click "Fix" to remove the config entry and clean up files. |
| **Integration removed from diff** | Error | When a core PR no longer modifies the tracked integration. Click "Fix" to remove. |
| **Download failed** | Error | When GitHub API requests fail 3+ times in a row. Auto-resolves when the next check succeeds. |
| **Token invalid** | Error | When the GitHub token expires or is revoked. Update via the options flow. |

## GitHub API Token

A GitHub personal access token is **required** during setup:

- Without authentication: 60 requests/hour (insufficient for polling)
- With personal access token: 5,000 requests/hour

**Create a dedicated token** for this integration. API rate limits are
per-token, so sharing a token with other applications could cause rate
limit issues.

### How to Create a Token

1. Go to [GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)](https://github.com/settings/tokens)
2. Click **Generate new token** > **Generate new token (classic)**
3. Give it a descriptive name (e.g., "Integration Tester - Home Assistant")
4. Set expiration as desired (or "No expiration" for convenience)
5. Select scope: **`public_repo`** (for public repos only) or **`repo`** (if you need access to private repos)
6. Click **Generate token** and copy it immediately (you won't see it again)

## FAQ

### What happens if the token expires?

A **Token invalid** repair issue is created. The integration will stop
polling for updates until you provide a new token via the options flow
(Settings > Devices & Services > Integration Tester > Configure on any
entry).

### What happens if I overwrite an integration managed by HACS?

Integration Tester will warn you if a `custom_components/` folder
already exists that it doesn't manage. In the UI you'll get a
confirmation dialog; via the `add` service, set `overwrite: true` to
proceed. Be aware that HACS may overwrite your version on its next
update, so it's best to remove the integration from HACS while testing.

### How does the `overwrite` flag work?

`overwrite` handles two scenarios:

- **Existing Integration Tester entry** for the same domain: the old entry is removed and replaced with the new one
- **Existing `custom_components/` folder** not managed by Integration
  Tester: the folder is replaced with the downloaded version

Without `overwrite`, both scenarios produce an error instead.

### How do I install from a core PR that modifies multiple integrations?

In the UI, you'll be shown a dropdown to select which integration to install. Via the `add` service, pass the `domain` parameter:

```yaml
service: integration_tester.add
data:
  url: "https://github.com/home-assistant/core/pull/12345"
  domain: "zwave_js"
```

### Can I keep the files after removing?

Yes. Use `delete_files: false` with the `remove` service:

```yaml
service: integration_tester.remove
data:
  domain: "my_integration"
  delete_files: false
```

This removes the config entry (stops polling, removes entities) but
leaves the integration files in `custom_components/`. The integration
will continue working but is no longer managed by Integration Tester.

### Are commits pinned?

Yes. When tracking a specific commit (not a branch or PR):

- No update entity is created (commits are immutable)
- To switch to a different commit, remove the config entry and add a new one

### Can I use this with non-GitHub repositories?

No. Only GitHub repositories are supported.

### Why does core require a PR URL?

For the home-assistant/core repository, Integration Tester needs to
determine which integration to extract. It does this by examining the
PR diff to see which files under `homeassistant/components/` are
modified. Branch and commit URLs don't provide this context.

## Contributing

Contributions are welcome! Please read the [contribution guidelines](CONTRIBUTING.md) first.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

[releases-shield]: https://img.shields.io/github/release/raman325/ha-integration-tester.svg
[releases]: https://github.com/raman325/ha-integration-tester/releases
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs]: https://github.com/custom-components/hacs
[license-shield]: https://img.shields.io/github/license/raman325/ha-integration-tester.svg
[license]: LICENSE
