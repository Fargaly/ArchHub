// Ephemeral capabilities inside the existing connection, never an identity store.
import crypto from 'node:crypto';

export class ScopedAttachments {
 constructor({connectionId,destination,now=Date.now}) {this.connectionId=connectionId;this.destination=destination;this.generation=crypto.randomUUID();this.now=now;this.grants=new Map();}
 issue(instanceId,ttlSeconds=300) {
  if(typeof instanceId!=='string'||!instanceId.trim()||instanceId.length>200)throw new Error('Invalid enrolled instance');
  if(!Number.isInteger(ttlSeconds)||ttlSeconds<1||ttlSeconds>900)throw new Error('Invalid attachment lifetime');
  for(const [key,value] of this.grants)if(value.expires_at<=this.now())this.grants.delete(key);
  if(this.grants.size>=8)throw new Error('Attachment capacity reached');
  const grant={connection_id:this.connectionId,connection_generation:this.generation,instance_id:instanceId,destination:this.destination,
   expires_at:this.now()+ttlSeconds*1000,token:crypto.randomBytes(32).toString('hex')};
  this.grants.set(grant.token,grant);return {...grant};
 }
 require(request) {
  const grant=this.grants.get(request.token);
  if(!grant||grant.expires_at<=this.now()||request.instance_id!==grant.instance_id||request.destination!==grant.destination||request.connection_id!==grant.connection_id||request.connection_generation!==grant.connection_generation)throw new Error('Attachment unavailable or scope changed');
  return grant;
 }
 revoke(request){this.require(request);this.grants.delete(request.token);return {revoked:true};}
 clear(){this.grants.clear();}
}
