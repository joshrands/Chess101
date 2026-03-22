# chess101.net Deployment Guide

Two deployment paths are documented here:

- **[Render](#render-recommended)** — managed hosting, automatic TLS, deploys from GitHub on push
- **[VPS](#vps-ubuntu-2204)** — self-hosted on any Ubuntu server

---

## Render (recommended)

Render deploys both services automatically from the `render.yaml` Blueprint at the
repo root whenever you push to the connected GitHub branch.

### Services

| Service | Type | Custom domain |
|---|---|---|
| `chess101-relay` | Web Service (Docker) | `relay.chess101.net` |
| `chess101-spectator` | Static Site | `chess101.net`, `www.chess101.net` |

The spectator page at `chess101.net` connects to the relay at `wss://relay.chess101.net`
by default. No path-based routing is needed — they are separate hostnames.

---

### 1. Connect the repo

1. Log into [render.com](https://render.com) and go to **New → Blueprint**.
2. Connect your GitHub repo. Render reads `render.yaml` and creates both services.

---

### 2. Configure environment variables

#### `chess101-relay` — Render dashboard → `chess101-relay` → **Environment**

| Variable | Required | Value | Description |
|---|---|---|---|
| `RELAY_PORT` | No | — | Render injects `PORT` automatically (e.g. `10000`); the relay falls back to it. Only set `RELAY_PORT` if you need to override the port. |
| `RELAY_MAX_ROOMS` | Yes | `200` | Maximum concurrent active rooms |
| `RELAY_ROOM_TIMEOUT` | Yes | `900` | Seconds of inactivity before a room is deleted |

> **Note:** Do not set `RELAY_PORT` on Render. The relay reads Render's `PORT` env var automatically. Setting `RELAY_PORT=8765` will cause the health check to fail because Render routes traffic to its own `PORT` (typically `10000`), not `8765`.

#### `chess101-spectator` — Render dashboard → `chess101-spectator` → **Environment**

| Variable | Value | Description |
|---|---|---|
| `SKIP_INSTALL_DEPS` | `true` | Prevents Render from auto-detecting and running `requirements.txt` (which would fail trying to build `pygame` for a server with no SDL). The static site is plain HTML and needs no Python dependencies. |

---

### 3. Set custom domains in the Render dashboard

#### `chess101-relay` — relay WebSocket service

1. Render dashboard → `chess101-relay` → **Custom Domains** → Add `relay.chess101.net`.
2. Render will display a CNAME target (e.g. `chess101-relay.onrender.com`).
3. At your DNS provider, add:

   ```
   Type   Host              Value
   CNAME  relay.chess101.net  chess101-relay.onrender.com
   ```

#### `chess101-spectator` — static site

1. Render dashboard → `chess101-spectator` → **Custom Domains** → Add `chess101.net` and `www.chess101.net`.
2. Render will display a CNAME target (e.g. `chess101-spectator.onrender.com`) and an IP address for the apex record.
3. At your DNS provider, add:

   ```
   Type   Host               Value
   ALIAS  chess101.net         chess101-spectator.onrender.com
   CNAME  www.chess101.net     chess101-spectator.onrender.com
   ```

   > **Apex records:** Most DNS providers support `ALIAS` or `ANAME` for bare domains.
   > If yours only supports `A` records at the apex, use the IP address Render provides
   > instead of the CNAME target.

Render provisions and renews TLS for all custom domains automatically — no Certbot needed.

---

### 4. Verify deployment

- **Relay logs**: Render dashboard → `chess101-relay` → **Logs**. You should see:
  ```
  relay listening on 0.0.0.0:8765
  ```
- **WebSocket smoke test** (requires `websocat`):
  ```bash
  websocat wss://relay.chess101.net
  ```
- **Spectator page**: visit `https://chess101.net`, enter a room code, and confirm
  the status line shows *Spectating room XXXXXX*.

---

### Updating

Push to the connected branch. Both services redeploy automatically.

---

## VPS (Ubuntu 22.04)

### Prerequisites

- A VPS with a public IP
- Domain `chess101.net` pointing to that IP
- Docker + Docker Compose installed
- Nginx installed (`apt install nginx`)
- Certbot installed (`apt install certbot python3-certbot-nginx`)

### 1. Clone the repo onto the server

```bash
git clone https://github.com/your-org/chess101.git /opt/chess101
cd /opt/chess101
```

### 2. Obtain TLS certificates (Let's Encrypt)

Run this once. Nginx must be reachable on port 80 for the ACME challenge.

```bash
ufw allow 80/tcp
certbot certonly --nginx -d chess101.net -d www.chess101.net
```

Certbot auto-renews via a systemd timer. Verify with:

```bash
certbot renew --dry-run
```

### 3. Configure Nginx

```bash
cp /opt/chess101/deploy/nginx.conf /etc/nginx/sites-available/chess101
ln -sf /etc/nginx/sites-available/chess101 /etc/nginx/sites-enabled/chess101
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
```

Copy the spectator page:

```bash
mkdir -p /var/www/chess101/web
cp /opt/chess101/web/spectator.html /var/www/chess101/web/
```

### 4. Build and run the relay container

```bash
cd /opt/chess101
docker build -f Dockerfile.relay -t chess101-relay .

docker run -d \
  --name chess101-relay \
  --restart unless-stopped \
  -p 127.0.0.1:8765:8765 \
  -e RELAY_PORT=8765 \
  -e RELAY_MAX_ROOMS=200 \
  -e RELAY_ROOM_TIMEOUT=900 \
  chess101-relay
```

The relay listens on `127.0.0.1:8765` (loopback only). Nginx proxies
`wss://chess101.net` → `ws://127.0.0.1:8765`.

### 5. Open the firewall

```bash
ufw allow 443/tcp
ufw allow 80/tcp
ufw reload
```

Port 8765 does **not** need to be open externally — Nginx proxies it.

### 6. Verify

```bash
docker ps | grep chess101-relay
docker logs chess101-relay
systemctl status nginx

# Quick WebSocket smoke test (requires websocat)
websocat wss://chess101.net
```

Open `https://chess101.net/spectate` in a browser and enter a room code.

### Updating (VPS)

```bash
cd /opt/chess101
git pull
docker build -f Dockerfile.relay -t chess101-relay .
docker stop chess101-relay && docker rm chess101-relay
docker run -d --name chess101-relay --restart unless-stopped \
  -p 127.0.0.1:8765:8765 \
  -e RELAY_PORT=8765 \
  -e RELAY_MAX_ROOMS=200 \
  -e RELAY_ROOM_TIMEOUT=900 \
  chess101-relay
```

---

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `RELAY_PORT` | `PORT` env → `8765` | Port the relay listens on. On Render, omit this — `PORT` is used automatically. On VPS, set to `8765` (or whichever port Nginx proxies to). |
| `RELAY_MAX_ROOMS` | `100` | Maximum concurrent active rooms |
| `RELAY_ROOM_TIMEOUT` | `600` | Seconds of inactivity before a room is deleted |
