// Isolated source-slice courts load the same DS dependency as the real Studio loader.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');
const ds = transformSync(fs.readFileSync(path.join(__dirname,'../nodelang/studio/ds/index.jsx'),'utf8'),{loader:'jsx'}).code;
function runInContext(code, context, options) {
  if (String(code).includes('window.AH_DS') && vm.runInContext("typeof window !== 'undefined' && !window.AH_DS",context)) {
    vm.runInContext("window.AH = window.AH || (typeof LM !== 'undefined' ? LM : {});",context);
    const react=vm.runInContext("typeof React !== 'undefined' ? React : window.React",context);
    if(react && !react.forwardRef) react.forwardRef=require('react').forwardRef;
    vm.runInContext(ds,context);
  }
  return vm.runInContext(code,context,options);
}
module.exports = {...vm, runInContext};
