import path from 'node:path';
import os from 'node:os';
export function stateDir(){
 const value=process.env.SESSION_LINK_STATE_DIR;
 if(!value||!path.isAbsolute(value))throw new Error('An absolute SESSION_LINK_STATE_DIR is required');
 return path.resolve(value);
}
export function userHome(){return process.env.USERPROFILE||os.homedir();}
