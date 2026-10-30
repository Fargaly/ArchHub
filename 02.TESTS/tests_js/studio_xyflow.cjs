// Browser-test harness: the same xyflow the Studio build bundles (compiled/xyflow.js when built,
// else the pinned npm package with the same jsx-runtime shim), so canvas tests load the real engine.
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const compiled = path.join(root, '01.APP/nodelang/studio/compiled');
const SHIM = 'window.jsxRuntime=window.jsxRuntime||{Fragment:React.Fragment,jsx:function(t,p,k){return React.createElement(t,'
  + 'k===undefined?p:Object.assign({},p,{key:k}));}};window.jsxRuntime.jsxs=window.jsxRuntime.jsx;\n';
const packageDir = () => path.dirname(require.resolve('@xyflow/react/package.json', {paths: [root, process.env.ARCHHUB_NODE_MODULES && path.dirname(process.env.ARCHHUB_NODE_MODULES)].filter(Boolean)}));
const read = (built, upstream) => fs.existsSync(path.join(compiled, built)) ? fs.readFileSync(path.join(compiled, built), 'utf8') : upstream();

module.exports = {
  script: () => read('xyflow.js', () => SHIM + fs.readFileSync(path.join(packageDir(), 'dist/umd/index.js'), 'utf8')),
  css: () => read('xyflow.css', () => fs.readFileSync(path.join(packageDir(), 'dist/base.css'), 'utf8')),
};
