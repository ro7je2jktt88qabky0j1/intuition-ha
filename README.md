# Intuition for Home Assistant

> Your home just knows.

Intuition is an AI-powered Home Assistant add-on that brings intelligent automation management, log analysis, and system health monitoring directly into your Home Assistant instance.

## Features

- **Log Review** — AI-powered analysis of your HA logs. Plain English explanations of errors, warnings, and recommendations.
- **Health Check** — Full system analysis across your automations, entities, logs, and hardware.
- **Entity Browser** — Browse and search all entities, devices, and areas.
- **Config File Viewer** — View all your YAML configuration files directly.
- **System Dashboard** — At-a-glance overview of your Home Assistant installation.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the menu (⋮) in the top right and select **Repositories**
3. Add this repository URL: `https://github.com/ro7je2jktt88qabky0j1/intuition-ha`
4. Find **Intuition** in the add-on store and click **Install**
5. In the add-on **Configuration** tab, enter your Claude API key
6. Start the add-on

## Configuration

| Option | Required | Description |
|--------|----------|-------------|
| `claude_api_key` | Yes | Your Anthropic Claude API key. Get one at [console.anthropic.com](https://console.anthropic.com) |
| `log_level` | No | Logging verbosity. Default: `info` |

## Getting a Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account or sign in
3. Go to **API Keys** and create a new key
4. Paste the key into the Intuition add-on configuration

## Roadmap

- [x] Phase 1: Foundation — Connect, entities, files, logs
- [x] Phase 2: Log Review — AI log analysis
- [x] Phase 3: Health Check — Full system health analysis
- [ ] Phase 4: Automation Assistant — Natural language automation management
- [ ] Phase 5: Trend Analysis — Device history and pattern detection

## Privacy

Your data stays on your local network. The only external call is to the Anthropic Claude API when you use AI features (Log Review, Health Check). Your HA token and configuration files are never sent to any third party.

## License

MIT
