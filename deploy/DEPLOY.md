# chess101.net Deployment Guide

## Prerequisites

- A VPS (Ubuntu 22.04 recommended) with a public IP
- Domain `chess101.net` pointing to that IP
- Docker + Docker Compose installed
- Nginx installed (`apt install nginx`)
- Certbot installed (`apt install certbot python3-certbot-nginx`)

---

## 1. Clone the repo onto the server

```bash
git clone https://github.com/your-org/chess101.git /opt/chess101
cd /opt/chess101
```

---

## 2. Obtain TLS certificates (Let's Encrypt)

Run this once. Nginx must be reachable on port 80 for the ACME challenge.

```bash
# Temporarily allow HTTP through the firewall if needed
ufw allow 80/tcp

certbot certonly --nginx -d chess101.net -d www.chess101.net
```

Certbot auto-renews via a systemd timer. Verify with:

```bash
certbot renew --dry-run
```

---

## 3. Configure Nginx

```bash
cp /opt/chess101/deploy/nginx.conf /etc/nginx/sites-available/chess101
ln -sf /etc/nginx/sites-available/chess101 /etc/nginx/sites-enabled/chess101
rm -f /etc/nginx/sites-enabled/default   # remove default site if present

nginx -t                  # verify config
systemctl reload nginx
```

The spectator page is served at `https://chess101.net/spectate`. Copy the web assets:

```bash
mkdir -p /var/www/chess101/web
cp /opt/chess101/web/spectator.html /var/www/chess101/web/
```

---

## 4. Build and run the relay container

```bash
cd /opt/chess101
docker build -f Dockerfile.relay -t chess101-relay .

docker run -d \
  --name chess101-relay \
  --restart unless-stopped \
  -p 127.0.0.1:8765:8765 \
  -e RELAY_MAX_ROOMS=200 \
  -e RELAY_ROOM_TIMEOUT=900 \
  chess101-relay
```

The relay listens on `127.0.0.1:8765` (loopback only). Nginx proxies
`wss://chess101.net` → `ws://127.0.0.1:8765`.

---

## 5. Open the firewall

```bash
ufw allow 443/tcp   # HTTPS / WSS
ufw allow 80/tcp    # HTTP (for ACME renewal)
ufw reload
```

Port 8765 does **not** need to be open externally — Nginx proxies it.

---

## 6. Verify

```bash
# Check relay is running
docker ps | grep chess101-relay
docker logs chess101-relay

# Check Nginx
systemctl status nginx

# Quick WebSocket smoke test (requires websocat)
websocat wss://chess101.net
```

Open `https://chess101.net/spectate` in a browser and enter a room code to
watch a live game.

---

## Updating the relay

```bash
cd /opt/chess101
git pull
docker build -f Dockerfile.relay -t chess101-relay .
docker stop chess101-relay && docker rm chess101-relay
docker run -d --name chess101-relay --restart unless-stopped \
  -p 127.0.0.1:8765:8765 chess101-relay
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RELAY_PORT` | `8765` | Port the relay listens on inside the container |
| `RELAY_MAX_ROOMS` | `100` | Maximum concurrent active rooms |
| `RELAY_ROOM_TIMEOUT` | `600` | Seconds of inactivity before a room is deleted |
