// Photon Spectrum iMessage sidecar for SWE-Jobs.
//
// Photon Spectrum's only send path is the spectrum-ts SDK holding a
// persistent connection (no plain REST send endpoint), so this small Node
// service owns that connection and exposes a loopback HTTP API to the
// Python backend — the same architecture the Hermes agent uses for iMessage.
//
//   POST /send   { "to": "+15551234567", "text": "..." }  -> { "ok": true }
//   GET  /health                                          -> { "ok": true }
//
// Inbound iMessages are forwarded to INBOUND_FORWARD_URL as:
//   { "from": "<sender>", "text": "...", "space_id": "...", "message_id": "..." }

import http from "node:http";
import { inboundSpool } from "./inbound-spool.js";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const PORT = Number(process.env.PORT || 8789);
const INBOUND_FORWARD_URL = process.env.INBOUND_FORWARD_URL || "";
const WEBHOOK_SECRET = process.env.IMESSAGE_WEBHOOK_SECRET || "";
const PROJECT_ID = process.env.SPECTRUM_PROJECT_ID || "";
const PROJECT_SECRET = process.env.SPECTRUM_PROJECT_SECRET || "";

if (!PROJECT_ID || !PROJECT_SECRET) {
  console.error("SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET are required");
  process.exit(1);
}

if (INBOUND_FORWARD_URL && !WEBHOOK_SECRET) {
  console.error("IMESSAGE_WEBHOOK_SECRET is required for inbound forwarding");
  process.exit(1);
}

const app = await Spectrum({
  projectId: PROJECT_ID,
  projectSecret: PROJECT_SECRET,
  providers: [imessage.config()],
});
const im = imessage(app);

async function sendIMessage(to, text) {
  const user = await im.user(to);
  const space = await im.space.create(user);
  await space.send(text);
}

const spool = inboundSpool(process.env.INBOUND_SPOOL_DIR || "/var/lib/swejobs/inbound", async (event) => {
  try {
    const response = await fetch(INBOUND_FORWARD_URL, {
      method: "POST",
      headers: {"content-type": "application/json", authorization: `Bearer ${WEBHOOK_SECRET}`},
      body: JSON.stringify(event),
      signal: AbortSignal.timeout(30000),
    });
    if (response.ok && (await response.json()).handled === true) return "ack";
    console.error("inbound event not acknowledged:", response.status);
    return response.status === 400 ? "reject" : "retry";
  } catch (err) {
    console.error("inbound forward attempt failed:", err);
    return "retry";
  }
});

function drainInbound() {
  spool.drain().catch(err => console.error("inbound spool drain failed:", err));
}

async function watchInbound() {
  for await (const [space, message] of app.messages) {
    try {
      if (message.direction === "outbound") continue;
      if (message?.content?.type !== "text") continue;
      const from = message.sender?.id;
      const text = message.content.text;
      if (!INBOUND_FORWARD_URL || !from || !text || !message.id) continue;
      await spool.enqueue({
        from,
        text,
        space_id: space?.id ?? null,
        message_id: message.id ?? null,
      });
    } catch (err) {
      throw err;
    }
  }
}

const server = http.createServer(async (req, res) => {
  res.setHeader("content-type", "application/json");

  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200);
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  if (req.method === "POST" && req.url === "/send") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let body;
    try {
      body = JSON.parse(raw || "{}");
    } catch {
      res.writeHead(200);
      res.end(JSON.stringify({ ok: false, error: "invalid_json" }));
      return;
    }
    const to = typeof body.to === "string" ? body.to.trim() : "";
    const text = typeof body.text === "string" ? body.text : "";
    if (!to || !text) {
      res.writeHead(200);
      res.end(JSON.stringify({ ok: false, error: "missing_to_or_text" }));
      return;
    }
    try {
      await sendIMessage(to, text);
      res.writeHead(200);
      res.end(JSON.stringify({ ok: true }));
    } catch (err) {
      console.error("send failed:", err);
      res.writeHead(200);
      res.end(JSON.stringify({ ok: false, error: String(err).slice(0, 500) }));
    }
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ ok: false, error: "not_found" }));
});

server.listen(PORT, () => {
  console.log(`imessage sidecar listening on :${PORT}`);
  if (INBOUND_FORWARD_URL) {
    drainInbound();
    setInterval(drainInbound, 5000).unref();
  }
  watchInbound().catch((err) => {
    console.error("inbound watcher exited:", err);
    process.exit(1);
  });
});
