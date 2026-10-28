// ArchHub Workshop live input for VS Code-family IDEs (Antigravity IDE today).
// A local named pipe takes one JSON line {token, text} and the text is submitted into the IDE's
// agent panel through the IDE's own registered command. No UI automation, no keyboard.
'use strict';
const vscode = require('vscode');
const net = require('net');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

// The IDE's own submit command per host (read from its shipped workbench bundle, called via the public commands API).
const SUBMIT = [
  { match: /antigravity/i, app: 'antigravity-ide', command: 'antigravity.sendPromptToAgentPanel',
    fresh: 'antigravity.startNewConversation' },
];

function discoveryDir() {
  return process.env.ARCHHUB_IDE_LIVE_DIR || path.join(os.homedir(), '.archhub-live');
}

function activate(context) {
  const host = SUBMIT.find((h) => h.match.test(vscode.env.appName));
  if (!host) return;
  const token = crypto.randomBytes(24).toString('hex');
  const pipe = '\\\\.\\pipe\\archhub-live-' + host.app + '-' + process.pid;
  const dir = discoveryDir();
  const file = path.join(dir, host.app + '-' + process.pid + '.json');
  const server = net.createServer((socket) => {
    let buf = '';
    socket.setEncoding('utf8');
    socket.on('data', async (chunk) => {
      buf += chunk;
      const nl = buf.indexOf('\n');
      if (nl < 0) return;
      let reply;
      try {
        const req = JSON.parse(buf.slice(0, nl));
        if (req.token !== token) reply = { status: 'failed', reason: 'unauthorized' };
        else if (typeof req.text !== 'string' || !req.text.trim()) reply = { status: 'failed', reason: 'empty message' };
        else {
          // fresh: open a new conversation first, so a message never lands in a thread the user is in.
          if (req.fresh && host.fresh) await vscode.commands.executeCommand(host.fresh);
          await vscode.commands.executeCommand(host.command, req.text);
          reply = { status: 'injected', at: Date.now(), command: host.command };
        }
      } catch (error) {
        reply = { status: 'failed', reason: String((error && error.message) || error).slice(0, 300) };
      }
      socket.end(JSON.stringify(reply) + '\n');
    });
    socket.on('error', () => {});
  });
  server.listen(pipe, () => {
    fs.mkdirSync(dir, { recursive: true });
    const workspace = (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
    fs.writeFileSync(file, JSON.stringify({ protocol: 1, app: host.app, appName: vscode.env.appName, pid: process.pid,
      pipe, token, workspace, command: host.command, createdAt: Date.now() }), { mode: 0o600 });
  });
  context.subscriptions.push({ dispose: () => { server.close(); try { fs.unlinkSync(file); } catch (error) { if (error.code !== 'ENOENT') console.error('archhub ide-live: could not remove ' + file, error); } } });
}

function deactivate() {}

module.exports = { activate, deactivate };
