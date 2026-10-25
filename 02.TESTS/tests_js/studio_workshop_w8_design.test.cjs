/* W8 design court: Workshop must present the design's visible structure using live projections.
   No canvas-node opening card; chat starts with the real ask, plan, Brain facts and task row. */
const {test} = require('node:test');
const assert = require('node:assert/strict');

const {transport, plain}=require('./workshop72_regression_helpers.cjs');

test('W8d Relay removal preserves the real cloud publish consent read and exact toggle authority',async()=>{
  const fx=transport({get:()=>({ok:true,allowed:false,account:'owner@example.com'}),post:(_url,body)=>({ok:true,allowed:body.allow,account:'owner@example.com'})});
  assert.deepEqual(plain(await fx.api.readCloudPublishConsent()),{allowed:false,account:'owner@example.com'});
  assert.deepEqual(plain(await fx.api.setCloudPublishConsent(true)),{allowed:true,account:'owner@example.com'});
  assert.deepEqual(fx.posts,[{url:'/api/universal/cloud-publish-consent',body:{allow:true}}]);
});
