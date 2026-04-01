import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const DEFAULT_DEVTOOLS_PATH = path.join(
  os.homedir(),
  'Library',
  'Application Support',
  'net.imput.helium',
  'DevToolsActivePort',
);
const DEVTOOLS_PATH = process.env.HELIUM_DEVTOOLS_ACTIVE_PORT || DEFAULT_DEVTOOLS_PATH;
const TIMEOUT_MS = 10000;

function fail(message, code = 1) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

if (typeof WebSocket !== 'function') {
  fail('Node.js with WebSocket support is required for Helium import.');
}
if (!fs.existsSync(DEVTOOLS_PATH)) {
  fail(`Helium DevToolsActivePort not found at ${DEVTOOLS_PATH}.`);
}

const devtoolsLines = fs.readFileSync(DEVTOOLS_PATH, 'utf8').trim().split('\n');
if (devtoolsLines.length < 2) {
  fail(`Invalid Helium DevToolsActivePort payload in ${DEVTOOLS_PATH}.`);
}

const [port, wsPath] = devtoolsLines;
const ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
const pending = new Map();
let nextId = 1;
let finished = false;

const timer = setTimeout(() => {
  finishError('Timed out while reading cookies from Helium.');
}, TIMEOUT_MS);

function finishOk(payload) {
  if (finished) return;
  finished = true;
  clearTimeout(timer);
  process.stdout.write(`${JSON.stringify(payload)}\n`);
  try {
    ws.close();
  } catch {
    // ignore
  }
  process.exit(0);
}

function finishError(message) {
  if (finished) return;
  finished = true;
  clearTimeout(timer);
  try {
    ws.close();
  } catch {
    // ignore
  }
  fail(message);
}

function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject, method });
  });
}

ws.addEventListener('open', async () => {
  try {
    const result = await send('Storage.getCookies', {});
    const cookies = Array.isArray(result.cookies) ? result.cookies : [];
    const filtered = cookies.filter((cookie) => {
      const domain = String(cookie.domain || '').toLowerCase();
      return domain.includes('openevidence.com');
    });
    finishOk({
      source: 'helium-live-cdp',
      cookies: filtered,
    });
  } catch (error) {
    finishError(error instanceof Error ? error.message : String(error));
  }
});

ws.addEventListener('message', (event) => {
  const message = JSON.parse(String(event.data));
  if (!message.id || !pending.has(message.id)) {
    return;
  }
  const { resolve, reject, method } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) {
    reject(new Error(`${method}: ${JSON.stringify(message.error)}`));
    return;
  }
  resolve(message.result);
});

ws.addEventListener('error', (event) => {
  finishError(event.message || event.error?.message || 'WebSocket connection to Helium failed.');
});
