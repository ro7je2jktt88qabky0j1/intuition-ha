# Intuition Changelog

## 2026.4.2
- AI Analysis now searches the web for actual release notes on pending updates
- Update cards show urgency level (ASAP / Apply Soon / When Convenient / Optional) with reasoning
- Update cards show risk assessment for applying and skipping each update
- Fixed pending updates and integration issues not appearing in AI Analysis

## 2026.4.1
- Switched to year.month.patch version numbering
- Dashboard status cards auto-populate on page load
- Removed redundant Refresh button from top bar
- Simplified status badge to green dot + "Connected"
- Removed sidebar stats section
- Added Refresh button to Entities and Config Files pages
- Sidebar reordered: Overview → Intelligence → Data
- Added Automation Status placeholder (coming soon)
- Fixed YAML viewer horizontal scrolling for wide files
- Fixed toolbar buttons being hidden on Config Files page
- File list simplified — full filename visible with line count

## 2.2.x
- Five status cards: System, Integrations, Backup, Logs, Resources
- Color coding: amber/red borders for cards needing attention
- System card shows pending update notice in amber
- Backup card colors by age: green <24h, amber 1-3 days, red 3+ days
- Resources card shows CPU, Memory, Disk with individual color thresholds
- Integration health monitoring via config entries API
- AI Analysis separated from status refresh — two distinct actions

## 2.0.0
- Complete dashboard redesign with two-section layout
- System Status section with live cards (no AI)
- AI Analysis section with persistent results and timestamp
- Health Check removed as separate AI page
- Automation Review placeholder added to Intelligence section
- Log Review unchanged — remains the deep dive AI tool

## 1.x
- Dynamic config file discovery following !include directives
- Integration health monitoring
- UniFi SuperLink sensor context in health check
- Fixed input_button trigger pattern recognition
- Health check prompt accuracy improvements

## 0.x — Initial Development
- Add-on skeleton and s6 service setup
- HA Supervisor API connection
- Entity browser with domain filters and search
- Config file viewer with line numbers and search
- System logs viewer
- Log Review — AI-powered log analysis
- Health Check — full system health analysis
