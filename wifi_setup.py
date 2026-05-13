#!/usr/bin/env python3
"""Chess101 WiFi captive portal.

When the Pi boots without a known WiFi network, this script creates an access
point called "Chess101-Setup" and serves a web page where users can enter WiFi
credentials. After saving, a "Restart" button reboots the Pi so it connects to
the new network on next boot.

Must run as root (hostapd, dnsmasq, interface configuration).
"""

import html
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

AP_SSID = "Chess101-Setup"
AP_IP = "192.168.4.1"
AP_CHANNEL = 7
WPA_CONF = "/etc/wpa_supplicant/wpa_supplicant.conf"
HOSTAPD_CONF = "/tmp/chess101_hostapd.conf"
DNSMASQ_CONF = "/tmp/chess101_dnsmasq.conf"
SAFETY_RESTORE_FILE = "/home/pi/Documents/Chess101/.wifi_safety_restore.conf"
HTTP_PORT = 80
SAFETY_TIMEOUT_S = 300

_networks = []
_saved_ssid = ""
_child_procs = []
_safety_timer = None


def scan_networks():
    """Scan for available WiFi networks before switching to AP mode."""
    global _networks
    try:
        result = subprocess.run(
            ["iwlist", "wlan0", "scan"],
            capture_output=True, text=True, timeout=15,
        )
        seen = {}
        ssid = ""
        quality = 0
        encrypted = False

        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Cell "):
                if ssid and (ssid not in seen or quality > seen[ssid]["quality"]):
                    seen[ssid] = {"ssid": ssid, "quality": quality, "encrypted": encrypted}
                ssid, quality, encrypted = "", 0, False
            elif "ESSID:" in stripped:
                try:
                    ssid = stripped.split('ESSID:"', 1)[1].rstrip('"')
                except IndexError:
                    ssid = ""
            elif "Quality=" in stripped:
                try:
                    q = stripped.split("Quality=", 1)[1].split(" ", 1)[0]
                    n, d = q.split("/")
                    quality = int(int(n) * 100 / int(d))
                except (ValueError, IndexError):
                    pass
            elif "Encryption key:on" in stripped:
                encrypted = True

        if ssid and (ssid not in seen or quality > seen[ssid]["quality"]):
            seen[ssid] = {"ssid": ssid, "quality": quality, "encrypted": encrypted}

        _networks = sorted(seen.values(), key=lambda x: x["quality"], reverse=True)
        print(f"Found {len(_networks)} networks")
    except Exception as e:
        print(f"WiFi scan failed: {e}")
        _networks = []


def start_ap():
    """Switch wlan0 to AP mode and start hostapd + dnsmasq."""
    subprocess.run(["killall", "-q", "hostapd"], capture_output=True)
    subprocess.run(["killall", "-q", "dnsmasq"], capture_output=True)
    subprocess.run(["killall", "-q", "wpa_supplicant"], capture_output=True)

    subprocess.run(["ip", "link", "set", "wlan0", "down"], capture_output=True)
    subprocess.run(["ip", "addr", "flush", "dev", "wlan0"], capture_output=True)
    subprocess.run(["ip", "addr", "add", f"{AP_IP}/24", "dev", "wlan0"],
                   capture_output=True)
    subprocess.run(["ip", "link", "set", "wlan0", "up"], capture_output=True)

    with open(HOSTAPD_CONF, "w") as f:
        f.write(
            f"interface=wlan0\n"
            f"driver=nl80211\n"
            f"ssid={AP_SSID}\n"
            f"hw_mode=g\n"
            f"channel={AP_CHANNEL}\n"
            f"wmm_enabled=0\n"
            f"macaddr_acl=0\n"
            f"auth_algs=1\n"
            f"ignore_broadcast_ssid=0\n"
        )

    with open(DNSMASQ_CONF, "w") as f:
        f.write(
            f"interface=wlan0\n"
            f"bind-interfaces\n"
            f"listen-address={AP_IP}\n"
            f"dhcp-range=192.168.4.2,192.168.4.20,24h\n"
            f"address=/#/{AP_IP}\n"
            f"no-resolv\n"
        )

    p1 = subprocess.Popen(["hostapd", HOSTAPD_CONF])
    _child_procs.append(p1)
    time.sleep(2)

    p2 = subprocess.Popen(["dnsmasq", "-C", DNSMASQ_CONF, "-k"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _child_procs.append(p2)
    time.sleep(1)

    print(f"Access point '{AP_SSID}' active at {AP_IP}")


def stop_ap():
    for p in _child_procs:
        try:
            p.terminate()
        except OSError:
            pass
    subprocess.run(["killall", "-q", "hostapd"], capture_output=True)
    subprocess.run(["killall", "-q", "dnsmasq"], capture_output=True)


def start_safety_timer():
    """Start a background timer that restores saved credentials and reboots.

    If a safety restore file exists (written before we removed a known network
    for testing), the timer will re-append those credentials and reboot after
    SAFETY_TIMEOUT_S seconds. This guarantees the Pi recovers even if the
    captive portal isn't used.

    Cancelled if the user saves credentials and reboots via the portal.
    """
    global _safety_timer
    if not os.path.exists(SAFETY_RESTORE_FILE):
        return

    def _restore():
        print(f"Safety timeout reached ({SAFETY_TIMEOUT_S}s) — restoring saved network and rebooting")
        with open(SAFETY_RESTORE_FILE) as f:
            block = f.read()
        with open(WPA_CONF, "a") as f:
            f.write(block)
        os.remove(SAFETY_RESTORE_FILE)
        subprocess.Popen(["sh", "-c", "sleep 2 && reboot"])

    _safety_timer = threading.Timer(SAFETY_TIMEOUT_S, _restore)
    _safety_timer.daemon = True
    _safety_timer.start()
    print(f"Safety timer started — will restore saved network in {SAFETY_TIMEOUT_S}s")


def cancel_safety_timer():
    global _safety_timer
    if _safety_timer is not None:
        _safety_timer.cancel()
        _safety_timer = None
        # Clean up the restore file since the user handled it
        if os.path.exists(SAFETY_RESTORE_FILE):
            os.remove(SAFETY_RESTORE_FILE)
        print("Safety timer cancelled")


def save_credentials(ssid, password):
    global _saved_ssid
    if password:
        block = (
            f'\nnetwork={{\n'
            f'\tssid="{ssid}"\n'
            f'\tpsk="{password}"\n'
            f'\tkey_mgmt=WPA-PSK\n'
            f'}}\n'
        )
    else:
        block = (
            f'\nnetwork={{\n'
            f'\tssid="{ssid}"\n'
            f'\tkey_mgmt=NONE\n'
            f'}}\n'
        )
    with open(WPA_CONF, "a") as f:
        f.write(block)
    _saved_ssid = ssid
    print(f"Saved credentials for '{ssid}'")


def signal_strength_bars(quality):
    if quality >= 75:
        return "&#9608;&#9608;&#9608;&#9608;"
    if quality >= 50:
        return "&#9608;&#9608;&#9608;&#9601;"
    if quality >= 25:
        return "&#9608;&#9608;&#9601;&#9601;"
    return "&#9608;&#9601;&#9601;&#9601;"


def render_portal():
    network_rows = ""
    for i, net in enumerate(_networks):
        esc = html.escape(net["ssid"], quote=True)
        bars = signal_strength_bars(net["quality"])
        lock = "&#128274; " if net["encrypted"] else ""
        network_rows += (
            f'<button type="button" class="net-row" onclick="selectNetwork(\'{esc}\')">'
            f'<span class="net-name">{esc}</span>'
            f'<span class="net-meta">{lock}<span class="bars">{bars}</span></span>'
            f'</button>\n'
        )

    if not network_rows:
        network_rows = '<p class="dimmed">No networks found in scan.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chess101 WiFi Setup</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
       display: flex; justify-content: center; padding: 24px 16px; }}
.card {{ background: #16213e; border-radius: 12px; padding: 28px 24px;
         max-width: 420px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
h1 {{ font-size: 22px; margin-bottom: 4px; color: #e2b714; }}
.subtitle {{ font-size: 14px; color: #8888a0; margin-bottom: 20px; }}
.net-list {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }}
.net-row {{ display: flex; align-items: center; gap: 10px; padding: 12px;
            background: #0f3460; border-radius: 8px; cursor: pointer;
            border: none; width: 100%; text-align: left; color: #e0e0e0; font-size: 15px; }}
.net-row:hover {{ background: #153b6e; }}
.net-name {{ flex: 1; }}
.net-meta {{ font-size: 13px; color: #8888a0; white-space: nowrap; }}
.bars {{ font-size: 10px; letter-spacing: -1px; }}
.dimmed {{ color: #666; font-size: 14px; margin-bottom: 12px; }}
.or-divider {{ text-align: center; color: #555; font-size: 13px; margin: 12px 0; }}
.manual-row {{ display: flex; gap: 8px; }}
.manual-row input {{ flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #2a2a4a;
                     background: #0f3460; color: #e0e0e0; font-size: 15px; }}
.manual-row input:focus {{ outline: none; border-color: #e2b714; }}
.manual-btn {{ padding: 12px 18px; border: none; border-radius: 8px; font-size: 15px;
               font-weight: 600; cursor: pointer; background: #e2b714; color: #1a1a2e;
               white-space: nowrap; }}
.manual-btn:hover {{ background: #f0c830; }}
.overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
            justify-content: center; align-items: center; padding: 16px; z-index: 10; }}
.overlay.active {{ display: flex; }}
.modal {{ background: #16213e; border-radius: 12px; padding: 24px; width: 100%;
          max-width: 380px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }}
.modal h2 {{ font-size: 18px; color: #e2b714; margin-bottom: 4px; }}
.modal .ssid-display {{ font-size: 14px; color: #8888a0; margin-bottom: 16px;
                        word-break: break-all; }}
.modal .field {{ margin-bottom: 16px; }}
.modal .field label {{ display: block; font-size: 13px; color: #8888a0; margin-bottom: 4px; }}
.modal .field input {{ width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #2a2a4a;
                       background: #0f3460; color: #e0e0e0; font-size: 16px; }}
.modal .field input:focus {{ outline: none; border-color: #e2b714; }}
.modal-actions {{ display: flex; gap: 10px; }}
.modal-actions button {{ flex: 1; padding: 12px; border: none; border-radius: 8px;
                         font-size: 16px; font-weight: 600; cursor: pointer; }}
.btn-connect {{ background: #e2b714; color: #1a1a2e; }}
.btn-connect:hover {{ background: #f0c830; }}
.btn-cancel {{ background: transparent; color: #8888a0; border: 1px solid #2a2a4a !important; }}
.btn-cancel:hover {{ background: #0f3460; }}
</style>
</head>
<body>
<div class="card">
  <h1>&#9822; Chess101</h1>
  <p class="subtitle">Select a WiFi network</p>
  <div class="net-list">
    {network_rows}
  </div>
  <div class="or-divider">&mdash; or enter manually &mdash;</div>
  <div class="manual-row">
    <input type="text" id="custom_ssid" placeholder="Network name">
    <button type="button" class="manual-btn" onclick="selectNetwork(document.getElementById('custom_ssid').value)">Connect</button>
  </div>
</div>

<div class="overlay" id="overlay">
  <div class="modal">
    <h2>Enter Password</h2>
    <p class="ssid-display" id="modal-ssid"></p>
    <form method="POST" action="/save" id="save-form">
      <input type="hidden" name="ssid" id="form-ssid">
      <div class="field">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" placeholder="WiFi password"
               autocomplete="off" autofocus>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn-cancel" onclick="closeModal()">Cancel</button>
        <button type="submit" class="btn-connect">Connect</button>
      </div>
    </form>
  </div>
</div>

<script>
function selectNetwork(ssid) {{
  ssid = ssid.trim();
  if (!ssid) return;
  document.getElementById("form-ssid").value = ssid;
  document.getElementById("modal-ssid").textContent = ssid;
  document.getElementById("password").value = "";
  document.getElementById("overlay").classList.add("active");
  setTimeout(function() {{ document.getElementById("password").focus(); }}, 100);
}}
function closeModal() {{
  document.getElementById("overlay").classList.remove("active");
}}
document.getElementById("overlay").addEventListener("click", function(e) {{
  if (e.target === this) closeModal();
}});
</script>
</body>
</html>"""


def render_saved():
    esc = html.escape(_saved_ssid)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chess101 WiFi Setup</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
       display: flex; justify-content: center; padding: 24px 16px; }}
.card {{ background: #16213e; border-radius: 12px; padding: 28px 24px;
         max-width: 420px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4);
         text-align: center; }}
h1 {{ font-size: 22px; margin-bottom: 4px; color: #e2b714; }}
.subtitle {{ font-size: 14px; color: #8888a0; margin-bottom: 24px; }}
.success {{ font-size: 16px; margin-bottom: 8px; color: #4ade80; }}
.detail {{ font-size: 14px; color: #8888a0; margin-bottom: 24px; }}
button {{ width: 100%; padding: 12px; border: none; border-radius: 8px;
          font-size: 16px; font-weight: 600; cursor: pointer; margin-bottom: 10px; }}
.restart {{ background: #e2b714; color: #1a1a2e; }}
.restart:hover {{ background: #f0c830; }}
.back {{ background: transparent; color: #8888a0; border: 1px solid #2a2a4a; }}
.back:hover {{ background: #0f3460; }}
</style>
</head>
<body>
<div class="card">
  <h1>&#9822; Chess101</h1>
  <p class="subtitle">WiFi Setup</p>
  <p class="success">&#10004; Network saved!</p>
  <p class="detail">"{esc}" has been added.<br>
     Restart the board to connect to it.</p>
  <form method="POST" action="/restart">
    <button type="submit" class="restart">Restart Board</button>
  </form>
  <form method="GET" action="/">
    <button type="submit" class="back">Add Another Network</button>
  </form>
</div>
</body>
</html>"""


def render_restarting():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chess101 Restarting</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
       display: flex; justify-content: center; align-items: center; padding: 24px 16px; }
.card { background: #16213e; border-radius: 12px; padding: 28px 24px;
        max-width: 420px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4);
        text-align: center; }
h1 { font-size: 22px; margin-bottom: 16px; color: #e2b714; }
.msg { font-size: 16px; color: #8888a0; }
.spinner { display: inline-block; width: 24px; height: 24px;
           border: 3px solid #2a2a4a; border-top-color: #e2b714;
           border-radius: 50%; animation: spin 1s linear infinite;
           margin-bottom: 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <div class="spinner"></div>
  <h1>Restarting&hellip;</h1>
  <p class="msg">The board is rebooting. You can disconnect from<br>
     "Chess101-Setup" and rejoin your normal WiFi.</p>
</div>
</body>
</html>"""


class CaptivePortalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if _saved_ssid:
            self._respond(render_saved())
        else:
            self._respond(render_portal())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        params = parse_qs(body)

        if self.path == "/save":
            ssid = params.get("ssid", [""])[0].strip()
            custom = params.get("custom_ssid", [""])[0].strip()
            password = params.get("password", [""])[0]
            if custom:
                ssid = custom
            if ssid:
                save_credentials(ssid, password)
            self._respond(render_saved() if _saved_ssid else render_portal())

        elif self.path == "/restart":
            cancel_safety_timer()
            self._respond(render_restarting())
            subprocess.Popen(["sh", "-c", "sleep 2 && reboot"])

        else:
            self._respond(render_portal())

    def _respond(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode())))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, fmt, *args):
        print(f"[captive-portal] {self.client_address[0]} {args[0]}")


def main():
    if os.geteuid() != 0:
        print("wifi_setup.py must run as root")
        sys.exit(1)

    def _cleanup(sig=None, frame=None):
        print("Stopping captive portal...")
        stop_ap()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    print("Scanning for WiFi networks...")
    scan_networks()

    print("Starting access point...")
    start_ap()

    start_safety_timer()

    print(f"Starting captive portal on http://{AP_IP}:{HTTP_PORT}")
    server = HTTPServer(("0.0.0.0", HTTP_PORT), CaptivePortalHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _cleanup()


if __name__ == "__main__":
    main()
