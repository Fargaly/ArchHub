import {PeerEndpoint,listClaudeSessions} from './vendor/src/peer-protocol.mjs';

// The interrupt is opt-in and Claude Code only. Claude Code aborts its running
// turn when a peer frame arrives with priority "now" (and the stop text becomes
// its next prompt); every other Session Link send stays "next". The frame is an
// ordinary peer frame with the sender's mode, so the receiver's own permission
// and hold rules still decide what happens to it.
// Codex Desktop runs turn/interrupt only on its own app-server and exposes no
// interrupt tool to other apps, so a Codex target is refused before anything is
// looked up or sent.
export const CODEX_INTERRUPT_REFUSAL='Codex Desktop does not expose interrupt to other apps; nothing sent';
const CLAUDE_ONLY='Interrupt is supported for Claude Code sessions only; nothing sent';

export function stopText(reason){
 if(typeof reason!=='string'||!reason.trim()||reason.length>2000)throw new Error('Stop reason must contain 1–2000 characters; nothing sent');
 return 'Stop: '+reason.trim();
}

async function sendStop(peer,socket,reason,permissionMode){
 const messageId=await peer.send(socket,stopText(reason),{priority:'now',permissionMode});
 return {messageId,priority:'now',status:'sent_unconfirmed',note:'Interrupt sent with priority now; the receiving session decides under its own permission and hold rules'};
}

export async function interrupt(app,session,reason,{permissionMode='prompting',catalogFn,sessionsFn=listClaudeSessions,endpointFn}={}){
 if(app==='codex')throw new Error(CODEX_INTERRUPT_REFUSAL);
 if(app!=='claude')throw new Error(CLAUDE_ONLY);
 if(typeof session!=='string'||!session.trim())throw new Error('Interrupt needs an exact target session; nothing sent');
 stopText(reason);
 if(!['prompting','bypass'].includes(permissionMode))throw new Error('Invalid sender permission mode; nothing sent');
 const all=await (catalogFn??(await import('./bridge.mjs')).catalog)({apps:['claude']});
 const matches=(all.claude||[]).filter(s=>s.id===session||s.selector===session||s.title===session);
 if(matches.length!==1)throw new Error('Interrupt target must resolve to exactly one live Claude Code session; nothing sent');
 const live=sessionsFn().find(s=>s.sessionId===matches[0].id);
 if(!live)throw new Error('Claude Code session went offline; nothing sent');
 const peer=endpointFn?endpointFn():new PeerEndpoint({name:'session-link-interrupt',cwd:process.cwd()});
 peer.permissionMode=permissionMode;
 await peer.start();
 try{return {target:matches[0].id,...await sendStop(peer,live.socket,reason,permissionMode)};}
 finally{peer.stop();}
}

// A bound Session Link connection: only a bound Claude Code remote can be
// interrupted; target() is the bridge's own bound-session resolver.
export async function interruptBound(binding,target,peer,{reason,permissionMode}={}){
 if((binding?.claude?.app||'claude')!=='claude')throw new Error(CLAUDE_ONLY);
 stopText(reason);
 const senderMode=permissionMode??peer.permissionMode;
 if(!['prompting','bypass'].includes(senderMode))throw new Error('Invalid sender permission mode; nothing sent');
 return await sendStop(peer,target().socket,reason,senderMode);
}
