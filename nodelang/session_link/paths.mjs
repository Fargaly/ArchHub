import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
export function stateDir(){
 const value=process.env.SESSION_LINK_STATE_DIR;
 if(!value||!path.isAbsolute(value))throw new Error('An absolute SESSION_LINK_STATE_DIR is required');
 return path.resolve(value);
}
// Message text for ask/answer/send/reply: exactly one of --file or --stdin.
// The text is data only: read as UTF-8, never evaluated or executed.
export const MESSAGE_LIMIT=32000;
export async function readMessage(args){
 const file=args.includes('--file'),stdin=args.includes('--stdin');
 if(file&&stdin)throw new Error('Use --file or --stdin, not both; not sent');
 if(!file&&!stdin)throw new Error('Message input required: --file UTF8_FILE or --stdin; not sent');
 if(!stdin)return fs.readFileSync(args[args.indexOf('--file')+1],'utf8');
 const text=await readStdinBounded(MESSAGE_LIMIT,stdinIdleMs());
 if(!text.trim())throw new Error('Empty stdin message; not sent');
 return text;
}
// A writer that stops sending without closing stdin is refused after this idle
// period. SESSION_LINK_STDIN_IDLE_MS may only shorten it (courts), never disable it.
export const STDIN_IDLE_MS=30000;
function stdinIdleMs(){
 const v=Number(process.env.SESSION_LINK_STDIN_IDLE_MS);
 return Number.isInteger(v)&&v>=100&&v<STDIN_IDLE_MS?v:STDIN_IDLE_MS;
}
// Streams stdin and refuses as soon as the text exceeds the limit, or when no
// data arrives for the idle period, without waiting for the writer to close.
// Bytes are decoded as UTF-8; the BOM, if any, is kept as data.
function readStdinBounded(limit,idleMs){
 return new Promise((resolve,reject)=>{
  const input=process.stdin,decoder=new TextDecoder('utf-8',{ignoreBOM:true});
  let text='',timer,settled=false;
  const finish=(error,value)=>{
   if(settled)return;settled=true;clearTimeout(timer);
   input.removeListener('data',onData);input.removeListener('end',onEnd);input.removeListener('error',onError);
   input.pause();if(error)input.destroy();
   error?reject(error):resolve(value);
  };
  const tooLong=()=>new Error('Text must contain 1-32000 characters; not sent');
  const arm=()=>{clearTimeout(timer);timer=setTimeout(()=>finish(new Error(`No stdin data for ${Math.round(idleMs/1000)} seconds and stdin was not closed; not sent`)),idleMs);};
  const onData=chunk=>{text+=decoder.decode(chunk,{stream:true});if(text.length>limit)return finish(tooLong());arm();};
  const onEnd=()=>{text+=decoder.decode();text.length>limit?finish(tooLong()):finish(null,text);};
  const onError=e=>finish(e);
  input.on('data',onData);input.on('end',onEnd);input.on('error',onError);
  arm();
 });
}
export function userHome(){return process.env.USERPROFILE||os.homedir();}
