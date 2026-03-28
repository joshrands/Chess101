/**
 * Node.js bridge for lockstep testing.
 *
 * Reads newline-delimited JSON from stdin, dispatches to the appropriate
 * JS function, and writes a JSON response to stdout.
 *
 * Protocol:
 *   stdin  <- {"op": "decode_frame", "rgba_b64": "...", "w": 320, "h": 240}
 *   stdout -> {"result": "ABCDEF"}  or  {"result": null}  or  {"error": "..."}
 */

"use strict";

const path = require("path");
const scanner = require(path.join(__dirname, "..", "web", "chessmatrix-scanner.js"));
const { decodeFrame } = scanner;

// ── helpers ────────────────────────────────────────────────────────────────

function respond(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

// ── op handlers ────────────────────────────────────────────────────────────

const OPS = {
  decode_frame(msg) {
    const rgba = Buffer.from(msg.rgba_b64, "base64");
    const result = decodeFrame(new Uint8Array(rgba), msg.w, msg.h);
    respond({ result: result || null });
  },

  ping() {
    respond({ result: "pong" });
  },
};

// ── main loop ──────────────────────────────────────────────────────────────

let buf = "";

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf("\n")) !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch (e) {
      respond({ error: `JSON parse error: ${e.message}` });
      continue;
    }
    const handler = OPS[msg.op];
    if (!handler) {
      respond({ error: `Unknown op: ${msg.op}` });
      continue;
    }
    try {
      handler(msg);
    } catch (e) {
      respond({ error: `${msg.op} threw: ${e.message}` });
    }
  }
});

process.stdin.on("end", () => process.exit(0));
