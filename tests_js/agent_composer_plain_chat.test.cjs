const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const composer = fs.readFileSync(path.join(__dirname, '../nodelang/agent_composer.py'), 'utf8');
const server = fs.readFileSync(path.join(__dirname, '../nodelang/application_server.py'), 'utf8');

test('composer prompt keeps plain conversation action-free', () => {
  assert.match(composer, /Propose actions ONLY when the user asks to change the canvas\./);
  assert.match(composer, /A remark, question, note or anything to remember gets \{"actions":\[\],"answer":"\.\.\."\}/);
});

test('composer keeps the model answer when draft issues exist', () => {
  const start = composer.indexOf('issues = [str(item["why"])');
  const body = composer.slice(start, composer.indexOf('return {', start));
  assert.match(body, /\(\(answer \+ " "\) if answer else ""\) \+ "Draft needs attention: "/);
  assert.doesNotMatch(body, /answer = "Draft needs attention: " \+ "; "\.join\(issues\)/);
});

test('node-scoped composer turns are stored on the node conversation', () => {
  const start = server.indexOf("if self.path == '/api/universal/agent':");
  const body = server.slice(start, server.indexOf("if self.path == '/api/universal/terminal':", start));
  assert.match(body, /conversation_root/);
  assert.match(body, /_turn_history\(/);
  assert.match(body, /_append_user\(/);
  assert.match(body, /conversation_context=conversation_context/);
  assert.match(body, /append_turn\("Model reply from %s:\\n%s"/);
});
