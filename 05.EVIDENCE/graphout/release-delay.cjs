// Diagnostic only: model a slow producer without loading the machine.
// shortcut: targets the current canvas-codex fixture; update the marker and replacement if that fixture changes.
const childProcess = require('node:child_process');
const spawn = childProcess.spawn;
childProcess.spawn = function (executable, args, options) {
  if (Array.isArray(args) && args[0] === '-u' && args[1] === '-c' && args[2].includes('canvas-codex')) {
    args = [...args];
    args[2] = args[2].replace("                    declare(0,'Export approved drawings')",
      "                    import time\n                    time.sleep(2.1)\n                    declare(0,'Export approved drawings')");
    if (!args[2].includes('time.sleep(2.1)')) throw Error('Producer delay was not installed');
  }
  return spawn.call(this, executable, args, options);
};
