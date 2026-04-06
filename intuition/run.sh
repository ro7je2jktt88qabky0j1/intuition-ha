#!/usr/bin/with-contenv bashio
# ==============================================================================
# Intuition - Your home just knows.
# ==============================================================================

# Read config
export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')

# Supervisor provides these
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export SUPERVISOR_URL="http://supervisor"

bashio::log.info "Starting Intuition v0.3.0..."

if bashio::config.is_empty 'claude_api_key'; then
    bashio::log.warning "Claude API key not configured - AI features unavailable."
fi

cd /app/backend
exec python3 main.py
