const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..', '..'),studio=path.join(root,'01.APP/nodelang','studio');
const originalRead=fs.readFileSync;
const sources=['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx','param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx','brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx','mount.jsx'];
const files=sources.map(source=>({source,output:source.replace(/\.jsx$/,'.js'),source_sha256:createHash('sha256').update(originalRead(path.join(studio,source))).digest('hex')}));
const cache=new Map();
fs.readFileSync=function(file,options){
 const normalized=String(file).replaceAll('\\','/');
 if(normalized.includes('/nodelang/studio/compiled/')){
  const name=normalized.split('/nodelang/studio/compiled/')[1];let text;
  if(name==='manifest.json')text=JSON.stringify({files});
  else {const row=files.find(row=>row.output===name);if(!row)return originalRead.apply(this,arguments);
   if(!cache.has(name))cache.set(name,require('esbuild').transformSync(originalRead(path.join(studio,row.source),'utf8'),{loader:'jsx',minifyWhitespace:true}).code);
   text=cache.get(name).replace('window.StudioLM=StudioLM}', 'window.StudioLM=StudioLM;}');
  }
  return options ? text : Buffer.from(text);
 }
 return originalRead.apply(this,arguments);
};
