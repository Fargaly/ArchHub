#!/usr/bin/env node
/**
 * from-brain.js — pulls community skills from the brain MCP daemon and writes
 * the COMMITTED static export src/data/skills-export.json (+ one MDX file
 * per skill under src/content/skills/ for future rich pages).
 *
 * This is an OPTIONAL maintainer step, invoked via `npm run refresh-content`
 * (or directly `node scripts/from-brain.js`). It is NOT part of the deploy
 * build — `astro build` reads the committed skills-export.json with NO daemon.
 * If the daemon is unreachable this script exits non-zero WITHOUT clobbering
 * the committed export, so a refresh run on a host without the brain keeps the
 * last honest data instead of zeroing it.
 *
 * Wire shape (see ArchHub/app/memory_gate.py BrainClient._call for reference):
 *   POST http://127.0.0.1:8473/mcp
 *   Headers: Content-Type: application/json
 *            Accept: application/json, text/event-stream
 *   Body: {"jsonrpc":"2.0","id":N,"method":"tools/call",
 *          "params":{"name":"brain.skill_export",
 *                    "arguments":{"scope":"community","limit":100}}}
 *   Response: text/event-stream
 *     event: message
 *     data: {"jsonrpc":"2.0","id":N,"result":{
 *              "content":[{"type":"text","text":"...json..."}],
 *              "structuredContent":{...},
 *              "isError":false}}
 *
 * Per CONTENT-ECOSYSTEM-2026-05-26.md §2:
 *   - Build step calls brain.skill_export
 *   - Each skill body → MDX feature page
 *   - Build fails loud if the brain daemon is unreachable (no stale-data publish)
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import http from 'node:http';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '..');
const CONTENT_DIR = path.join(PROJECT_ROOT, 'src', 'content', 'skills');
const EXPORT_JSON = path.join(PROJECT_ROOT, 'src', 'data', 'skills-export.json');

const BRAIN_HOST = process.env.BRAIN_HOST || '127.0.0.1';
const BRAIN_PORT = Number(process.env.BRAIN_PORT || 8473);
const BRAIN_PATH = '/mcp';
const SCOPE = process.env.BRAIN_SKILL_SCOPE || 'community';
const LIMIT = Number(process.env.BRAIN_SKILL_LIMIT || 100);

/**
 * Call an MCP tool over Streamable HTTP. Mirrors BrainClient._call:
 * sends JSON-RPC with Accept: text/event-stream, parses the SSE
 * `data:` line, prefers structuredContent.
 */
function mcpCall(tool, args) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: { name: tool, arguments: args || {} },
    });
    const req = http.request(
      {
        hostname: BRAIN_HOST,
        port: BRAIN_PORT,
        path: BRAIN_PATH,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json, text/event-stream',
          'Content-Length': Buffer.byteLength(payload),
        },
      },
      (res) => {
        let raw = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { raw += chunk; });
        res.on('end', () => {
          // Parse SSE — extract JSON from `data:` lines.
          let data = null;
          for (const line of raw.split(/\r?\n/)) {
            const s = line.trim();
            if (!s.startsWith('data:')) continue;
            try {
              const obj = JSON.parse(s.slice(5).trim());
              if (obj && obj.jsonrpc === '2.0') { data = obj; break; }
            } catch {}
          }
          // Fallback: plain JSON body (non-SSE server).
          if (data == null) {
            try { data = JSON.parse(raw); } catch {
              return reject(new Error(`unparseable brain response: ${raw.slice(0, 200)}`));
            }
          }
          if (data.error) return reject(new Error(JSON.stringify(data.error)));
          const result = data.result || {};
          if (result.isError) return reject(new Error(JSON.stringify(result.content || 'tool error')));
          if (result.structuredContent) return resolve(result.structuredContent);
          // Fallback: parse text content[0]
          const content = result.content || [];
          if (content[0] && typeof content[0].text === 'string') {
            try { return resolve(JSON.parse(content[0].text)); }
            catch { return resolve({ text: content[0].text }); }
          }
          resolve(result);
        });
      },
    );
    req.setTimeout(5000, () => req.destroy(new Error('brain call timeout')));
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

function frontmatter(obj) {
  const lines = ['---'];
  for (const [k, v] of Object.entries(obj)) {
    if (v == null) continue;
    if (Array.isArray(v)) {
      lines.push(`${k}:`);
      for (const item of v) lines.push(`  - ${JSON.stringify(String(item))}`);
    } else {
      lines.push(`${k}: ${JSON.stringify(v)}`);
    }
  }
  lines.push('---', '');
  return lines.join('\n');
}

function escapeMdx(s) {
  // MDX is JSX-aware — escape stray `{` and `<` to keep it as text.
  return String(s || '').replace(/[{}]/g, (c) => `\\${c}`);
}

async function main() {
  // 1. Health check — fail loud if brain is down (per CONTENT-ECOSYSTEM §2:
  //    "if down, build fails fast (no stale-data publish)").
  console.log(`[from-brain] probing brain at http://${BRAIN_HOST}:${BRAIN_PORT}/mcp ...`);
  let health;
  try {
    health = await mcpCall('brain.health', {});
  } catch (e) {
    console.error(`[from-brain] FAIL — brain unreachable: ${e.message}`);
    console.error(`[from-brain] start the daemon: cd ArchHub/personal-brain-mcp && PYTHONPATH=src python -m personal_brain.server --http 8473`);
    process.exit(1);
  }
  console.log(`[from-brain] brain OK — version=${health.version} skills=${health.skills} db=${health.db_path}`);

  // 2. Export skills at the requested scope.
  console.log(`[from-brain] calling brain.skill_export(scope=${SCOPE}, limit=${LIMIT}) ...`);
  let exp;
  try {
    exp = await mcpCall('brain.skill_export', { scope: SCOPE, limit: LIMIT });
  } catch (e) {
    console.error(`[from-brain] FAIL — brain.skill_export rejected: ${e.message}`);
    process.exit(2);
  }
  if (!exp.ok) {
    console.error(`[from-brain] brain.skill_export returned ok=false: ${exp.error || JSON.stringify(exp)}`);
    process.exit(3);
  }

  fs.mkdirSync(CONTENT_DIR, { recursive: true });

  // 3. Write each skill to src/content/skills/<id>.mdx
  const skills = exp.skills || [];
  console.log(`[from-brain] writing ${skills.length} skill(s) → ${CONTENT_DIR}`);
  for (const sk of skills) {
    const safeId = String(sk.id || sk.name || 'unknown')
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .slice(0, 80);
    const file = path.join(CONTENT_DIR, `${safeId}.mdx`);
    const fm = frontmatter({
      id: sk.id,
      name: sk.name,
      description: sk.description,
      scope: sk.scope,
      contributor: sk.contributor,
      firm_id: sk.firm_id,
      triggers: sk.triggers,
      requires_mcps: sk.requires_mcps,
      exported_at: exp.exported_at,
    });
    const body = `# ${escapeMdx(sk.name)}\n\n${escapeMdx(sk.description)}\n\n## How it works\n\n${escapeMdx(sk.body)}\n`;
    fs.writeFileSync(file, fm + body, 'utf8');
  }

  // 4. Persist the COMMITTED static export the site reads at build time.
  //    /features renders straight from this — count 0 => honest empty state.
  const exportPayload = {
    exported_at: exp.exported_at,
    scope: SCOPE,
    count: skills.length,
    source: 'brain.skill_export(scope=community) via scripts/from-brain.js',
    note: skills.length === 0
      ? 'No community skills published to the federation yet — /features renders an honest empty state.'
      : `${skills.length} community skill(s) exported from the brain.`,
    skills: skills.map((sk) => ({
      id: sk.id,
      name: sk.name,
      description: sk.description,
      scope: sk.scope,
      contributor: sk.contributor,
      triggers: sk.triggers,
      requires_mcps: sk.requires_mcps,
    })),
  };
  fs.writeFileSync(EXPORT_JSON, JSON.stringify(exportPayload, null, 2) + '\n', 'utf8');
  console.log(`[from-brain] DONE — ${skills.length} skill(s) written, export @ src/data/skills-export.json`);
}

main().catch((e) => {
  console.error(`[from-brain] crash: ${e.stack || e.message}`);
  process.exit(99);
});
