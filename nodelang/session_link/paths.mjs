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
export function readMessage(args){
 const file=args.includes('--file'),stdin=args.includes('--stdin');
 if(file&&stdin)throw new Error('Use --file or --stdin, not both; not sent');
 if(!file&&!stdin)throw new Error('Message input required: --file UTF8_FILE or --stdin; not sent');
 if(!stdin)return fs.readFileSync(args[args.indexOf('--file')+1],'utf8');
 const text=fs.readFileSync(0,'utf8');
 if(!text.trim())throw new Error('Empty stdin message; not sent');
 if(text.length>MESSAGE_LIMIT)throw new Error('Text must contain 1-32000 characters; not sent');
 return text;
}
export function userHome(){return process.env.USERPROFILE||os.homedir();}
