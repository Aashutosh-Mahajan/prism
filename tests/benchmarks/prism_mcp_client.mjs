/** A persistent, protocol-level MCP stdio client for the live agent benchmark.
 * The agent imports this adapter once, then calls the server's listed tools.
 * JSONL traffic is recorded separately for MCP call counts and timing.
 */
import { spawn } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { createInterface } from 'node:readline';

export async function connectPrism(root, config, trace, python = 'C:/Python314/python.exe') {
  const server = spawn(python, ['-u', '-c',
    'from pathlib import Path; from prism.mcp.server import run; run(Path.cwd())'], {
    cwd: root,
    env: {
      PRISM_CONFIG_HOME: config,
      PYTHONPATH: 'D:/Projects/prism;C:/Users/mahaj/AppData/Roaming/Python/Python314/site-packages',
      SYSTEMROOT: 'C:/Windows', USERPROFILE: 'C:/Users/mahaj',
      APPDATA: 'C:/Users/mahaj/AppData/Roaming', LOCALAPPDATA: 'C:/Users/mahaj/AppData/Local',
      TEMP: 'C:/Users/mahaj/AppData/Local/Temp', TMP: 'C:/Users/mahaj/AppData/Local/Temp',
      PATH: 'C:/Python314;C:/Windows/System32',
    },
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let nextId = 0;
  let closed = false;
  let stderr = '';
  const pending = new Map();
  const log = (direction, message) => appendFileSync(trace,
    JSON.stringify({ timestamp: new Date().toISOString(), direction, message }) + '\n');
  log('lifecycle', { event: 'server_started', pid: server.pid, root });
  server.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-8000); });
  createInterface({ input: server.stdout }).on('line', line => {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    log('receive', message);
    if (message.id !== undefined && pending.has(message.id)) {
      const item = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(item.timer);
      if (message.error) item.reject(new Error(JSON.stringify(message.error)));
      else item.resolve(message.result);
    }
  });
  const fail = error => {
    closed = true;
    for (const item of pending.values()) {
      clearTimeout(item.timer);
      item.reject(error);
    }
    pending.clear();
  };
  server.on('error', fail);
  server.on('exit', (code, signal) => {
    log('lifecycle', { event: 'server_exit', code, signal });
    fail(new Error(`MCP server exited (${code}, ${signal}): ${stderr}`));
  });
  function send(message) {
    if (closed) throw new Error('MCP server is closed');
    log('send', message);
    server.stdin.write(JSON.stringify(message) + '\n');
  }
  function request(method, params = {}) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`MCP request timed out: ${method}`));
      }, 30000);
      pending.set(id, { resolve, reject, timer });
      send({ jsonrpc: '2.0', id, method, params });
    });
  }
  try {
    const initialization = await request('initialize', {
      protocolVersion: '2024-11-05', capabilities: {},
      clientInfo: { name: 'codex-prism-agent-benchmark', version: '1.0' },
    });
    send({ jsonrpc: '2.0', method: 'notifications/initialized' });
    const listing = await request('tools/list');
    const allowed = new Set(['prism_status', 'prism_brief', 'prism_search', 'prism_locate',
      'prism_context', 'prism_impact', 'prism_module']);
    const tools = listing.tools.filter(tool => allowed.has(tool.name));
    return {
      initialization, tools, pid: server.pid,
      async call(name, args = {}) {
        if (!allowed.has(name)) throw new Error(`Tool disallowed in diagnosis benchmark: ${name}`);
        const result = await request('tools/call', { name, arguments: args });
        // Return one structured representation rather than duplicate JSON + text.
        if (result.structuredContent !== undefined) return result.structuredContent;
        const text = (result.content || []).filter(item => item.type === 'text').map(item => item.text).join('\n');
        try { return JSON.parse(text); } catch { return { isError: !!result.isError, text }; }
      },
      close() {
        if (!closed) {
          log('lifecycle', { event: 'client_close' });
          server.stdin.end();
          server.kill();
        }
      },
    };
  } catch (error) {
    server.kill();
    throw error;
  }
}
