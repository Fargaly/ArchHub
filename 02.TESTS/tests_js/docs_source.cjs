// Tests read the real shared tutorials; no second prose fixture can drift.
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const localPython = path.join(process.env.LOCALAPPDATA || '', 'ArchHub', '.venv', 'Scripts', 'python.exe');
const python = process.env.ARCHHUB_TEST_PYTHON || (fs.existsSync(localPython) ? localPython : 'python');
module.exports = JSON.parse(execFileSync(python, ['-c',
  'import json;from nodelang.site_export import project_documentation;print(json.dumps(project_documentation()))'],
  {cwd:path.resolve(__dirname, '..', '..'), encoding:'utf8', timeout:30000}));
