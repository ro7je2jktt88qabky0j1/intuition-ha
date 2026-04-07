#!/usr/bin/with-contenv bashio
# ==============================================================================
# Intuition - Your home just knows.
# ==============================================================================

export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export SUPERVISOR_URL="http://supervisor"
export INGRESS_ENTRY=$(bashio::addon.ingress_entry)

# Read version dynamically from config.yaml
VERSION=$(bashio::addon.version)
export INTUITION_VERSION="${VERSION}"

bashio::log.info "Starting Intuition v${VERSION}..."
bashio::log.info "Ingress entry: ${INGRESS_ENTRY}"

if bashio::config.is_empty 'claude_api_key'; then
    bashio::log.warning "Claude API key not configured - AI features unavailable."
    bashio::log.warning "Add your key in the add-on Configuration tab."
fi

cd /app/backend
exec python3 main.py
