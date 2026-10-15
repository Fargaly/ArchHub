/* Render-only catalogue reader. Synthetic court identities remain in plateFixture(). */
const {spawnSync}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
function renderModels(run=spawnSync){
  const script=`import json, urllib.request
from nodelang.model_catalogue import openrouter_models
rows = openrouter_models(opener=urllib.request.urlopen, timeout=25)
print(json.dumps(rows))`;
  const result=run(process.env.ARCHHUB_RENDER_PYTHON||'python',['-c',script],{
    cwd:root,encoding:'utf8',timeout:40000,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  if(result.error||result.status!==0)throw new Error('Render model catalogue unavailable');
  const models=JSON.parse(result.stdout).filter(row=>row.cost==='free'&&row.route&&row.name);
  if(models.length<3)throw new Error('Render requires three free model catalogue entries');
  return models;
}
module.exports={renderModels};
