// Official SDK: https://opencode.ai/docs/sdk/ — session.prompt body.model.
// Explicit opt-in only; no session/global configuration or automatic fallback.
export const FREE_MODEL_IDS = Object.freeze([
 'qwen/qwen3.8-27b:free', 'nex-agi/nex-n2.5-pro:free',
 'thinkingmachines/inkling:free', 'poolside/laguna-s-2.1:free',
]);
export function validateModel(model) {
 if (model === undefined) return undefined;
 if (!model || typeof model !== 'object' || Array.isArray(model) ||
     Object.keys(model).sort().join(',') !== 'modelID,providerID' ||
     model.providerID !== 'openrouter' || !FREE_MODEL_IDS.includes(model.modelID))
  throw new Error('Explicit model must be an approved exact free OpenRouter selection; not sent');
 return {providerID:model.providerID,modelID:model.modelID};
}
export function modelFromOptions(provider,model) {
 return provider === undefined && model === undefined ? undefined : validateModel({providerID:provider,modelID:model});
}
export function modelFromArgs(args) {
 for(const flag of ['--provider','--model']) {
  const indices=args.flatMap((value,index)=>value===flag?[index]:[]);
  if(indices.length>1 || (indices.length===1 && (!args[indices[0]+1] || args[indices[0]+1].startsWith('--'))))
   throw new Error('Missing or duplicate explicit model option; not sent');
 }
 const value=flag=>{const index=args.indexOf(flag);return index<0?undefined:args[index+1];};
 return modelFromOptions(value('--provider'),value('--model'));
}
export function formatModelReceipt(answer) {
 return answer.model_receipt?`\n[${answer.status}; model receipt ${JSON.stringify(answer.model_receipt)}]`:'';
}
export async function promptSelectedModel(client, {id,directory,text,model}, fetcher=fetch) {
 const selected=validateModel(model);
 await verifyFreeModel(selected,fetcher);
 return await client.session.prompt({path:{id},query:{directory},
  body:{parts:[{type:'text',text}],...(selected?{model:selected}:{})}});
}
export async function verifyFreeModel(model, fetcher=fetch) {
 const selected=validateModel(model);
 if (!selected) return;
 const response=await fetcher('https://openrouter.ai/api/v1/models', {signal:AbortSignal.timeout(8000)});
 if (!response.ok) throw new Error('Free model catalogue unavailable; not sent');
 // Stream and cap the public catalogue; never inspect credentials/configuration.
 const reader=response.body.getReader();let size=0;const chunks=[];
 try {for (;;) {const {done,value}=await reader.read();if(done)break;
  size+=value.byteLength;if(size>8*1024*1024)throw new Error('Free model catalogue exceeds bound; not sent');chunks.push(Buffer.from(value));}}
 finally {await reader.cancel().catch(()=>{});}
 const data=JSON.parse(Buffer.concat(chunks).toString('utf8')).data;
 const rows=Array.isArray(data)?data.filter(row=>row.id===selected.modelID):[];
 const zero=value=>(typeof value==='number'||typeof value==='string') &&
  /^(?:0+(?:\.0+)?)(?:[eE][+-]?\d+)?$/.test(String(value)) && Number(value)===0;
 if(rows.length!==1 || !zero(rows[0].pricing?.prompt) || !zero(rows[0].pricing?.completion) ||
    !Object.values(rows[0].pricing).every(zero) ||
    !Array.isArray(rows[0].supported_parameters) || !rows[0].supported_parameters.includes('tools'))
  throw new Error('Model is unavailable, not zero-priced or lacks tools; not sent');
}
export async function sendSelectedOpenCode(rpc,request,model,onDispatch=()=>{}) {
 const selected=validateModel(model);
 if(selected) {
  const capabilities=await rpc({operation:'capabilities'});
  if(capabilities?.per_request_free_model!==1)
   throw new Error('Running OpenCode plugin lacks explicit free-model support; not sent');
 }
 // This marks a potentially effectful plugin RPC, not proof of model dispatch:
 // the plugin still validates live pricing before session.prompt. No retry.
 onDispatch();
 return await rpc({...request,...(selected?{model:selected}:{})});
}
export function modelReceipt(result,model,rows) {
 if(model===undefined)return result;
 const selected=validateModel(model);
 const actual=rows.map(row=>({message_id:row.id,providerID:row.providerID,modelID:row.modelID}));
 const verified=actual.length>0 && actual.every(row=>row.providerID===selected.providerID && row.modelID===selected.modelID);
 return {...result,status:verified?'model_selection_verified':'model_selection_failed',
  model_receipt:{requested:selected,actual,verified}};
}
