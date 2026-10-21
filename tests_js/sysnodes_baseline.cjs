/* Read-only cb3193bb preloader for comparing the selected related courts.
   No working-tree replacement and no generated compiler output is written. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..'),base='cb3193bb';
const original=fs.readFileSync.bind(fs),cache=new Map(),compiled=new Map();
const names=new Set(['nodelang/studio/studio-lm.jsx','nodelang/studio/studio-params.jsx',
  'nodelang/studio/studio.html','nodelang/studio/studio-authority.js','nodelang/studio/studio-existing-workshop.js']);
const bytes=name=>{
  if(!cache.has(name))cache.set(name,execFileSync('git',['show',base+':'+name],{cwd:root,maxBuffer:4*1024*1024}));
  return cache.get(name);
};
const hash=buffer=>createHash('sha256').update(buffer).digest('hex');
let Babel;
function output(source){
  if(!compiled.has(source)){
    if(!Babel){Babel={};vm.runInNewContext(original(path.join(root,'nodelang/studio/vendor/babel.js'),'utf8'),{exports:Babel,module:{exports:Babel}});}
    const sourcePath='nodelang/studio/'+source;
    const code=Babel.transform(bytes(sourcePath).toString('utf8'),{presets:['react','env'],
      plugins:['transform-class-properties','transform-object-rest-spread','transform-flow-strip-types'],targets:{},sourceMaps:false,
      filename:'/studio/'+source,sourceFileName:'/studio/'+source}).code;
    compiled.set(source,Buffer.from(code));
  }
  return compiled.get(source);
}
const encode=(value,options)=>{
  const encoding=typeof options==='string'?options:options?.encoding;
  return encoding?value.toString(encoding):Buffer.from(value);
};
fs.readFileSync=function(filename,options){
  if(typeof filename!=='string')return original(filename,options);
  const relative=path.relative(root,path.resolve(filename)).replaceAll('\\','/');
  if(names.has(relative))return encode(bytes(relative),options);
  if(relative==='nodelang/studio/compiled/studio-lm.js')return encode(output('studio-lm.jsx'),options);
  if(relative==='nodelang/studio/compiled/studio-params.js')return encode(output('studio-params.jsx'),options);
  if(relative==='nodelang/studio/compiled/manifest.json'){
    const manifest=JSON.parse(original(filename,'utf8'));
    for(const entry of manifest.files){
      if(!['studio-lm.jsx','studio-params.jsx'].includes(entry.source))continue;
      const source=bytes('nodelang/studio/'+entry.source),code=output(entry.source);
      Object.assign(entry,{source_bytes:source.length,source_sha256:hash(source),bytes:code.length,sha256:hash(code),
        integrity:'sha256-'+createHash('sha256').update(code).digest('base64')});
    }
    if(manifest.inputs?.loader){const source=bytes('nodelang/studio/studio.html');
      Object.assign(manifest.inputs.loader,{bytes:source.length,sha256:hash(source)});}
    return encode(Buffer.from(JSON.stringify(manifest)),options);
  }
  return original(filename,options);
};
