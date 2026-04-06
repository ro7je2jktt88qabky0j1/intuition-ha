#!/usr/bin/with-contenv bashio
# ==============================================================================
# Intuition - Your home just knows.
# ==============================================================================

export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export SUPERVISOR_URL="http://supervisor"

# Get the ingress entry point for correct URL routing
export INGRESS_ENTRY=$(bashio::addon.ingress_entry)

bashio::log.info "Starting Intuition v0.9.0..."
bashio::log.info "Ingress entry: ${INGRESS_ENTRY}"

if bashio::config.is_empty 'claude_api_key'; then
    bashio::log.warning "Claude API key not configured - AI features unavailable."
fi

cd /app/backend
exec python3 main.py
