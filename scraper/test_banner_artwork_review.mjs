// Run: node --test scraper/test_banner_artwork_review.mjs
// Full request-level checks with an in-memory Cloudflare KV substitute.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';

if (!globalThis.crypto)globalThis.crypto=webcrypto;
const moduleCode=await readFile(new URL('../functions/api/banner-claims.js',import.meta.url),'utf8');
const {onRequestPost,onRequestGet}=await import('data:text/javascript;base64,'+Buffer.from(moduleCode).toString('base64'));
const editorHtml=await readFile(new URL('../editor/banner-bookings.html',import.meta.url),'utf8');

class FakeKV {
 constructor(){this.store=new Map();}
 async get(k,opts){const value=this.store.get(k);return opts?.type==='json'?(value?JSON.parse(value):null):(value??null);}
 async put(k,v){this.store.set(k,v);}
}
const logo='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9j6FCV0AAAAASUVORK5CYII=';
function futureMonth(){const d=new Date();d.setUTCMonth(d.getUTCMonth()+2,1);return d.toISOString().slice(0,7);}
function request(body,token){return new Request('https://rochdaledaily.co.uk/api/banner-claims',{method:'POST',headers:{'Content-Type':'application/json',...(token?{'x-admin-token':token}:{})},body:JSON.stringify(body)});}
function getRequest(params='',token){return new Request('https://rochdaledaily.co.uk/api/banner-claims'+params,{headers:token?{'x-admin-token':token}:{}});}
test('pending logo is admin-only; approve requires review of the currently submitted revision',async()=>{
 const kv=new FakeKV(),env={EVENTS_ADMIN_TOKEN:'test-administrator',EVENTS_KV:kv};
 const post=(body,token)=>onRequestPost({request:request(body,token),env});
 const get=(p,token)=>onRequestGet({request:getRequest(p,token),env});
 const submit=await post({action:'submit',name:'Example Firm',email:'ads@example.co.uk',website:'https://example.co.uk',top:'A local service',bottom:'Reserve a quote',colour:'#132c4e',logo,month:futureMonth()});
 assert.equal(submit.status,201);
 const {reference:id,editToken}=await submit.json();
 const paid=await post({action:'mark-paid',id,paymentReference:'sumup-test-001'},'test-administrator');
 assert.equal(paid.status,200);
 const premature=await post({action:'approve',id},'test-administrator');
 assert.equal(premature.status,409);
 assert.match((await premature.json()).error,/Preview and review/i);

 const noAuth=await get('?preview-logo=1&id='+encodeURIComponent(id));
 assert.equal(noAuth.status,401);
 const invalidAuth=await get('?preview-logo=1&id='+encodeURIComponent(id),'wrong');
 assert.equal(invalidAuth.status,401);
 const authorized=await get('?preview-logo=1&id='+encodeURIComponent(id),'test-administrator');
 assert.equal(authorized.status,200);
 assert.equal(authorized.headers.get('Content-Type'),'image/png');
 assert.match(authorized.headers.get('Cache-Control'),/no-store/);
 assert.equal(new Uint8Array(await authorized.arrayBuffer())[0],0x89);

 const stale=await post({action:'review-artwork',id,revision:2},'test-administrator');
 assert.equal(stale.status,409);
 const review=await post({action:'review-artwork',id,revision:1},'test-administrator');
 assert.equal(review.status,200);
 assert.equal((await review.json()).artworkReviewedRevision,1);
 const approved=await post({action:'approve',id},'test-administrator');
 assert.equal(approved.status,200);

 const edit=await post({action:'edit',id,token:editToken,top:'New headline',bottom:'New second message',colour:'#204060'});
 assert.equal(edit.status,200);
 const queue=await get('', 'test-administrator');
 assert.equal(queue.status,200);
 const {claims}=await queue.json();
 const row=claims.find(x=>x.id===id);
 assert.equal(row.revision,2);
 assert.equal(row.status,'pending');
 assert.equal(row.artworkReviewedAt,null);
 assert.equal(row.artworkReviewedRevision,null);
 assert.equal(row.paymentStatus,'paid');
 assert.equal(row.top,'New headline');
 const invalidAfterEdit=await post({action:'approve',id},'test-administrator');
 assert.equal(invalidAfterEdit.status,409);
 const oldReview=await post({action:'review-artwork',id,revision:1},'test-administrator');
 assert.equal(oldReview.status,409);
 const newReview=await post({action:'review-artwork',id,revision:2},'test-administrator');
 assert.equal(newReview.status,200);
 assert.equal((await post({action:'approve',id},'test-administrator')).status,200);
});
test('editor shows current copy and colour, authenticates logo fetch and disables approval until preview',()=>{
 for(const field of ['item.top','item.bottom','item.colour','preview-logo=1','x-admin-token','review-artwork','previewReady','approveButton.disabled=true','Promise.all([imageLoaded']){
  assert.ok(editorHtml.includes(field),'Missing UI feature: '+field);
 }
 assert.ok(!editorHtml.includes('item.logo='),'Logo must not be present as an inline data URL');
});
