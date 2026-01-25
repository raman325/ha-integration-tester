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

## Features

### Sensors

| Sensor | Description |
|--------|-------------|
| Commit | Current installed commit hash (with attributes for full hash, message, author, etc.) |
| Last Push | Timestamp of the last push to the tracked branch/PR |

### Update Entity

For branches and PRs (not commits), an update entity tracks when new commits are available:

- Checks every 5 minutes for updates
- Manual check available via "Check for updates" in the UI
- Detects force pushes (compares commit SHA, not git history)

### Repair Issues

The integration creates repair issues for:

- **Restart required** - After installing/updating, click to restart HA
- **PR merged/closed** - When a tracked PR is no longer open
- **Integration removed from diff** - When a core PR no longer modifies the tracked integration
- **Download failed** - When GitHub API requests fail repeatedly

## Important Notes

### GitHub API Token Required

A GitHub personal access token is **required** during setup:

- Without authentication: 60 requests/hour (insufficient for polling)
- With personal access token: 5,000 requests/hour

Once configured, the token can always be updated later via any Integration Tester config entry options flow.

**Important:** Create a dedicated token for this integration.
API rate limits are per-token, so sharing a token with other applications could cause rate limit issues.

#### How to Create a Token

1. Go to [GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)](https://github.com/settings/tokens)
2. Click **Generate new token** > **Generate new token (classic)**
3. Give it a descriptive name (e.g., "Integration Tester - Home Assistant")
4. Set expiration as desired (or "No expiration" for convenience)
5. Select scope: **`public_repo`** (for public repos only) or **`repo`** (if you need access to private repos)
6. Click **Generate token** and copy it immediately (you won't see it again)

### Commits Are Pinned

When tracking a specific commit (not a branch or PR):

- No update entity is created
- The commit is immutable - if someone amends and force-pushes, the original commit still exists
- To switch to the amended commit, remove the config entry and add a new one

### HACS Conflicts

If you're testing a PR for an integration you have installed via HACS:

1. Remove it from HACS first, or be aware that HACS updates could overwrite your PR version
2. Once done testing, delete from Integration Tester and re-add via HACS
3. You may need to reconfigure the integration depending on changes between versions

### Only GitHub Supported

This integration only supports GitHub repositories.

## Troubleshooting

### "manifest.json not found"

The repository must have the standard structure: `custom_components/<domain>/manifest.json`

### "For Home Assistant core, please use a PR URL"

For core repository, we need a PR to determine which integration to extract. Branch/commit URLs for core are not supported.

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
