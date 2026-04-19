# HIL (Hardware-In-The-Loop) Docker image for Chess101
#
# Reproduces a close approximation of the Raspberry Pi 3+ environment:
#   - ARM64 Debian Jessie (archived repos) - Pi 3+ CPU is ARMv8/ARM64 capable
#   - OpenSSL 1.1.1w built from source (Pi's old OpenSSL 1.0.1t is too old)
#   - Python 3.9.21 built from source with the new OpenSSL
#   - Same library versions as the physical Pi
#
# Build on Apple Silicon Mac (runs natively, no QEMU needed):
#   docker buildx build --platform linux/arm64 -t chess101-hil -f hil/Dockerfile .

# -----------------------------------------------------------------------------
# Stage 1: Build OpenSSL 1.1.1w from source on ARM64 Debian Jessie
# -----------------------------------------------------------------------------
FROM arm64v8/debian:jessie AS openssl-builder

# Jessie repos are archived - use only main repo (no security repo for archived distros)
RUN echo "deb http://archive.debian.org/debian jessie main" > /etc/apt/sources.list

# Disable release-file valid check (archived repos have expired signatures)
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

# Install build dependencies for OpenSSL
RUN apt-get update && apt-get install -y --force-yes --allow-unauthenticated \
    build-essential \
    wget \
    ca-certificates \
    perl \
    && rm -rf /var/lib/apt/lists/*

# Build OpenSSL 1.1.1w from source (matches Pi setup)
WORKDIR /build
RUN wget --no-check-certificate https://www.openssl.org/source/openssl-1.1.1w.tar.gz && \
    tar xzf openssl-1.1.1w.tar.gz && \
    cd openssl-1.1.1w && \
    ./config --prefix=/usr/local/ssl --openssldir=/usr/local/ssl shared && \
    make -j$(nproc) && \
    make install && \
    rm -rf /build

# -----------------------------------------------------------------------------
# Stage 2: Build Python 3.9.21 from source with custom OpenSSL
# -----------------------------------------------------------------------------
FROM arm64v8/debian:jessie AS python-builder

# Copy OpenSSL from builder stage
COPY --from=openssl-builder /usr/local/ssl /usr/local/ssl

# Update ld.so.conf to find the new OpenSSL libs
RUN echo "/usr/local/ssl/lib" > /etc/ld.so.conf.d/openssl.conf && ldconfig

# Jessie repos are archived
RUN echo "deb http://archive.debian.org/debian jessie main" > /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

# Install build dependencies for Python
RUN apt-get update && apt-get install -y --force-yes --allow-unauthenticated \
    build-essential \
    wget \
    ca-certificates \
    libffi-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libgdbm-dev \
    liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

# Build Python 3.9.21 from source (matches Pi setup exactly)
WORKDIR /build
RUN wget --no-check-certificate https://www.python.org/ftp/python/3.9.21/Python-3.9.21.tgz && \
    tar xzf Python-3.9.21.tgz && \
    cd Python-3.9.21 && \
    ./configure --with-openssl=/usr/local/ssl --with-ensurepip=install && \
    make -j$(nproc) && \
    make install && \
    rm -rf /build

# -----------------------------------------------------------------------------
# Stage 3: Runtime image
# -----------------------------------------------------------------------------
FROM arm64v8/debian:jessie

# Copy OpenSSL and Python from builder stages
COPY --from=openssl-builder /usr/local/ssl /usr/local/ssl
COPY --from=python-builder /usr/local /usr/local

# Update ld.so.conf to find the custom OpenSSL libs
RUN echo "/usr/local/ssl/lib" > /etc/ld.so.conf.d/openssl.conf && ldconfig

# Update archived repos and disable signature check
RUN echo "deb http://archive.debian.org/debian jessie main" > /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

# Install runtime dependencies (ca-certificates needed for SSL to relay)
RUN apt-get update && apt-get install -y --force-yes --allow-unauthenticated \
    libffi6 \
    zlib1g \
    libsqlite3-0 \
    libreadline6 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates

# Upgrade pip and install Python packages (certifi for modern CA bundle)
RUN /usr/local/bin/pip3 install --no-cache-dir --upgrade pip && \
    /usr/local/bin/pip3 install --no-cache-dir \
    websockets>=12.0 \
    numpy \
    certifi \
    chessmatrix

# Use certifi's CA bundle for SSL (Jessie's ca-certificates too old for modern certs)
ENV SSL_CERT_FILE=/usr/local/lib/python3.9/site-packages/certifi/cacert.pem
ENV REQUESTS_CA_BUNDLE=/usr/local/lib/python3.9/site-packages/certifi/cacert.pem

WORKDIR /app

# Copy game code (order matters for layer caching)
COPY core/ ./core/
COPY pieces/ ./pieces/
COPY ai/ ./ai/
COPY hardware/ ./hardware/
COPY ui/ ./ui/
COPY network/ ./network/
COPY game/ ./game/
COPY hil/ ./hil/
COPY harness/ ./harness/
COPY GameManager.py samplebase.py ./

# Environment variables
ENV HIL_PORT=8766
ENV HIL_FAST_MODE=0
ENV PYTHONUNBUFFERED=1

EXPOSE 8766

# Health check via WebSocket ping
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD /usr/local/bin/python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 8766)); s.close()" || exit 1

CMD ["/usr/local/bin/python3", "-m", "hil.run_hil"]
