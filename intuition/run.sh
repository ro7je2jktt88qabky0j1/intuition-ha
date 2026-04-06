#!/usr/bin/with-contenv bashio
# ==============================================================================
# Intuition - Your home just knows.
# Starts the Python/FastAPI backend
# ==============================================================================

# Read add-on config options
export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')

# HA Supervisor provides these automatically
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export SUPERVISOR_URL="http://supervisor"

bashio::log.info "Starting Intuition v0.1.0..."
bashio::log.info "Log level: ${LOG_LEVEL}"

if bashio::config.is_empty 'claude_api_key'; then
    bashio::log.warning "Claude API key not set. AI features will be unavailable."
    bashio::log.warning "Add your key in the add-on Configuration tab."
fi

# Change to backend directory and start
cd /app/backend || bashio::exit.nok "Failed to enter backend directory"

exec python3 main.py
