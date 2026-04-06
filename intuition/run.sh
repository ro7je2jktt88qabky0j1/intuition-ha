#!/usr/bin/with-contenv bashio

# Read config options
export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')

# HA connection - provided automatically by Supervisor
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export SUPERVISOR_URL="http://supervisor"

bashio::log.info "Starting Intuition..."
bashio::log.info "Log level: ${LOG_LEVEL}"

# Start the backend
exec python3 /app/backend/main.py
