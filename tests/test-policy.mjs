import assert from 'node:assert/strict';
import {decide} from '../web/policy.mjs';
for(const cloud of ['working','none','unknown']){
 for(const curated of [true,false]){
  assert.equal(decide({cloud,curated,override:'include'}).status,'Included');
  assert.equal(decide({cloud,curated,override:'exclude'}).status,'Excluded');
  assert.equal(decide({cloud,curated,override:'auto'}).status,curated?'Included':cloud==='working'?'Excluded':cloud==='none'?'Included':'Review');
 }
}
console.log('18 precedence and coverage cases passed');
