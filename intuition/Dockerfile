ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-setuptools \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY backend/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Copy application files
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Set up s6 service directory
RUN mkdir -p /etc/services.d/intuition

# Copy run script into s6 service
COPY run.sh /etc/services.d/intuition/run
RUN chmod +x /etc/services.d/intuition/run

# Create s6 finish script
RUN printf '#!/usr/bin/with-contenv bashio\nbashio::log.info "Intuition service stopped."\n' \
    > /etc/services.d/intuition/finish && \
    chmod +x /etc/services.d/intuition/finish
