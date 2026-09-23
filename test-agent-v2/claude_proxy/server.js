// OpenAI-compatible shim over the local `claude` CLI (subscription). Lets the Dockerised agents use
// your Claude subscription: litellm POSTs /v1/chat/completions here, we shell `claude -p` (which uses
// the persisted ~/.claude login) and return the completion. Text-only, non-streaming — enough for the
// engine's complete() path and ADK LlmAgent text calls. Auth lives in a mounted volume (/root/.claude);
// run the one-time `claude /login` via `docker compose exec` (see README).
const http = require('http');
const { execFile } = require('child_process');

const PORT = process.env.PORT || 8088;

function flatten(messages) {
  return (messages || []).map(m => {
    const role = m.role === 'system' ? 'System' : m.role === 'assistant' ? 'Assistant' : 'User';
    const c = Array.isArray(m.content) ? m.content.map(x => x.text || '').join('') : (m.content || '');
    return `${role}: ${c}`;
  }).join('\n\n');
}

function runClaude(prompt) {
  return new Promise((resolve, reject) => {
    const args = ['-p', prompt, '--output-format', 'json'];
    if (process.env.CLAUDE_MODEL) args.push('--model', process.env.CLAUDE_MODEL);
    execFile('claude', args, { maxBuffer: 64 * 1024 * 1024, timeout: 600000 }, (err, out, errout) => {
      if (err) return reject(new Error(errout || err.message));
      try { const j = JSON.parse(out); resolve(j.result ?? j.response ?? out); }
      catch { resolve(out); }
    });
  });
}

http.createServer((req, res) => {
  if (req.url === '/health' || req.url === '/livez') { res.writeHead(200); return res.end('ok'); }
  if (req.method === 'POST' && req.url.startsWith('/v1/chat/completions')) {
    let body = '';
    req.on('data', c => (body += c));
    req.on('end', async () => {
      try {
        const { messages } = JSON.parse(body || '{}');
        const text = await runClaude(flatten(messages));
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          id: 'claude-local', object: 'chat.completion', created: 0, model: 'claude-local',
          choices: [{ index: 0, message: { role: 'assistant', content: text }, finish_reason: 'stop' }],
          usage: {},
        }));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: String(e && e.message || e) } }));
      }
    });
    return;
  }
  res.writeHead(404); res.end('not found');
}).listen(PORT, '0.0.0.0', () => console.log('claude-proxy on :' + PORT));
