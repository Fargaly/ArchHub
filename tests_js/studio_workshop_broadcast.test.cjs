/* The founder asked why he has to choose one agent to speak in the Workshop. He does not:
   the owner records a message with no named recipient, and every attached participant reads it
   (the transcript shows it as "to Everyone"). These courts bind the default and the two shapes
   the transport may send: [] for the Workshop, [root] for one addressed agent. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

// The shipped transport's own send body, built by the slice that composes it.
const transportSource = read('nodelang/studio/studio-existing-workshop.js');

function sendBody(target) {
  const start = transportSource.indexOf('// No target is the Workshop itself');
  const end = transportSource.indexOf('const pendingKey =', start);
  assert.ok(start > 0 && end > start, 'the recipient rule is a slice of the shipped transport');
  const context = vm.createContext({
    details:{target, message:'hello everyone'},
    held:{participants:[{root:'agent-a', attached:true}, {root:'agent-b', attached:true}]},
    root:'room-a', stamp:{scope:'scope-a'}, category:'note',
    text:value => typeof value === 'string' && value.length > 0,
    fail:message => { throw new Error(message); },
  });
  vm.runInContext(transportSource.slice(start, end) + '\nglobalThis.body = body;', context);
  return JSON.parse(JSON.stringify(context.body));
}

test('no chosen participant sends to the Workshop, and every attached agent reads it', () => {
  assert.deepEqual(sendBody('').recipients, [], 'no named recipient: the Workshop itself');
  assert.equal(sendBody('').text, 'hello everyone');
});

test('a chosen participant is addressed alone', () => {
  assert.deepEqual(sendBody('agent-a').recipients, ['agent-a']);
});

test('a participant who is not in this Workshop is still refused', () => {
  assert.throws(() => sendBody('ghost'), /Choose a current participant/);
});

test('the composer opens addressed to the Workshop, not to one pre-picked agent', () => {
  const view = read('nodelang/studio/studio-workshop.jsx');
  assert.match(view, /<option value="">to: Workshop \(everyone\)<\/option>/);
  assert.equal(view.includes("setTarget('model:' + modelAgent.root)"), false,
    'opening a room no longer pre-addresses one model agent');
  assert.equal(view.includes('Choose a participant before sending.'), false,
    'sending without a pick is no longer refused');
});
