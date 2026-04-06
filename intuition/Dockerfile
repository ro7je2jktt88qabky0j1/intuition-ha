ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python3 and build dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev

# Install Python packages
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Copy app files
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY run.sh /run.sh
RUN chmod a+x /run.sh
