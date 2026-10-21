import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {collectOpenCodeTurn} from './opencode-plugin.mjs';

const singletonKey=Symbol.for('archhub.session-link.opencodeserver');
const migrationKey=Symbol.for('archhub.session-link.opencode.scoped-turn-migration');
const refuse=why=>{throw new Error('OpenCode scoped migration: '+why);};
const unwrap=value=>{if(value?.error)refuse('native read refused');return value?.data??value;};

// Run inside the existing plugin host only. This never opens a model session,
// replaces a shared server, loads governance hooks, or changes native permissions.
export async function installScopedOpenCodeTurnMigration({stateDirectory,directory,sessionId,runtimeId}) {
 if(!path.isAbsolute(stateDirectory)||!path.isAbsolute(directory)||
    !/^ses_[A-Za-z0-9]+$/.test(sessionId)||runtimeId!==process.pid)refuse('exact native scope required');
 const singleton=globalThis[singletonKey];
 if(!singleton||!(singleton.clients instanceof Map))refuse('existing singleton unavailable');
 if(singleton[migrationKey])refuse('a scoped migration is already retained');
 const runtimeFile=path.join(stateDirectory,'opencode-runtimes',runtimeId+'.json');
 const verifyRuntime=()=>{
  let record;try{record=JSON.parse(fs.readFileSync(runtimeFile,'utf8'));}catch{refuse('runtime record unavailable');}
  if(globalThis[singletonKey]!==singleton||!singleton.server?.listening||
     record.pid!==runtimeId||typeof record.control!=='string'||
     singleton.server.address()!==record.control||
     typeof record.keyPath!=='string'||singleton.peer?.keyPath!==record.keyPath||
     singleton.peer?.name!=='opencode-session-link-'+runtimeId||
     (singleton.stateDirectory!==undefined&&singleton.stateDirectory!==stateDirectory))refuse('runtime identity changed');
 };
 verifyRuntime();
 const original=singleton.clients.get(directory);
 if(!original?.session||!['get','status','prompt','messages'].every(k=>typeof original.session[k]==='function'))refuse('attached native client unavailable');

 // Same lock namespace as sendExtra. A retained uncertain dispatch is never
 // removed automatically. Direct SDK callers are outside this transport lease.
 const lockDir=path.join(stateDirectory,'dispatch-locks');fs.mkdirSync(lockDir,{recursive:true});
 const lock=path.join(lockDir,crypto.createHash('sha256').update('opencode|'+sessionId).digest('hex')+'.json');
 const lease=crypto.randomUUID();
 let fd;try{fd=fs.openSync(lock,'wx');}catch{refuse('session dispatch lease unavailable');}
 try{fs.writeFileSync(fd,JSON.stringify({pid:process.pid,app:'opencode',session:sessionId,migration:lease}));}finally{fs.closeSync(fd);}
 const releaseLease=()=>{
  // Refuse deleting another actor's replacement lock, including during rollback.
  let value;try{value=JSON.parse(fs.readFileSync(lock,'utf8'));}catch{refuse('dispatch lease changed');}
  if(value.migration!==lease)refuse('dispatch lease changed');
  fs.unlinkSync(lock);
 };
 let installed=false;
 try {
  const native=unwrap(await original.session.get({path:{id:sessionId},query:{directory},signal:AbortSignal.timeout(10000)}));
  if(native?.id!==sessionId||native?.directory!==directory)refuse('native session/workspace mismatch');
  const statuses=unwrap(await original.session.status({query:{directory},signal:AbortSignal.timeout(10000)}));
  if(!statuses||typeof statuses!=='object'||Array.isArray(statuses)||
     (statuses[sessionId]&&statuses[sessionId].type!=='idle'))refuse('native session is busy or held');
  verifyRuntime();
  if(singleton[migrationKey])refuse('a scoped migration appeared during inspection');
  if(singleton.clients.get(directory)!==original)refuse('attached client changed during inspection');
  const state={active:0,uncertain:false,restored:false,lastFinal:null};
  const nativeSession=original.session;
  const prompt=async(...args)=>{
   const request=args[0];
   if(request?.path?.id!==sessionId)return Reflect.apply(nativeSession.prompt,nativeSession,args);
   if(request?.query?.directory!==directory)refuse('target prompt workspace mismatch; not sent');
   if(state.restored||state.uncertain||state.active)refuse('target migration is unavailable; not sent');
   verifyRuntime();
   if(singleton.clients.get(directory)!==facade)refuse('scoped client changed; not sent');
   state.active++;
   try{
    const response=await Reflect.apply(nativeSession.prompt,nativeSession,args);
    if(response?.error){state.uncertain=true;return response;}
    const reply=response?.data??response;
    state.lastFinal=typeof reply?.info?.id==='string'?reply.info.id:null;
    const result=await collectOpenCodeTurn(original,{sessionId,directory,reply});
    // The retained legacy handler reads only text from reply.parts. This is a
    // transport projection, never written to the native conversation history.
    const projected={...reply,parts:[{type:'text',text:result.text}]};
    return response?.data!==undefined?{...response,data:projected}:projected;
   }catch(error){state.uncertain=true;throw error;}
   finally{state.active--;}
  };
  // Bind all other SDK methods to their original receiver. Only prompt for the
  // exact selected session changes; other directory Map entries are untouched.
  const forward=(target,overrides)=>{
   const bound=new Map();
   return new Proxy(target,{get(object,key){
    if(Object.hasOwn(overrides,key))return overrides[key];
    const value=Reflect.get(object,key,object);
    if(typeof value!=='function')return value;
    if(!bound.has(key)||bound.get(key).source!==value)bound.set(key,{source:value,value:value.bind(object)});
    return bound.get(key).value;
   }});
  };
  const facade=forward(original,{session:forward(nativeSession,{prompt})});
  const handle=Object.freeze({
   status:()=>({sessionId,directory,runtimeId,active:state.active,uncertain:state.uncertain,
    restored:state.restored,lastFinal:state.lastFinal}),
   rollback:()=>{
    if(state.active||state.uncertain)refuse('target outcome requires reconciliation; migration retained');
    verifyRuntime();
    if(state.restored||singleton.clients.get(directory)!==facade)refuse('scoped client changed; rollback refused');
    singleton.clients.set(directory,original);state.restored=true;delete singleton[migrationKey];
   }
  });
  singleton.clients.set(directory,facade);singleton[migrationKey]=handle;installed=true;
  return handle;
 }finally{
  try{releaseLease();}catch(error){
   // A failed lease release does not undo a possibly active client projection.
   if(installed)throw new Error('OpenCode scoped migration installed; dispatch lease requires reconciliation');
   throw error;
  }
 }
}
