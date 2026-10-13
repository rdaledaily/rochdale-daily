'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.hidden=false;this.value='';this.listeners={};this.className='';this.style={};this.classList={toggle:()=>{},add:()=>{},remove:()=>{}};}
 set textContent(v){this.text=String(v);this.children=[];}get textContent(){return (this.text||'')+this.children.map(c=>c.textContent||'').join(' ');}
 append(...c){this.children.push(...c);}replaceChildren(...c){this.text='';this.children=c;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}querySelectorAll(s){const all=this.children.flatMap(c=>[c,...(c.querySelectorAll?.('*')||[])]);return s==='*'?all:all.filter(c=>s==='button'?c.tagName==='BUTTON':s==='.tab'?c.className==='tab':false);}
 addEventListener(t,f){this.listeners[t]=f;}scrollIntoView(){}focus(){}
}
function dashboard(fetcher){
 const elements={};for(const [,id] of fs.readFileSync('my-rochdale.html','utf8').matchAll(/id="([^"]+)"/g))elements[id]=new Element();
 elements.lookup.append(new Element('button'));
 const context={window:{RD_LOCAL_SNAPSHOT:{wards:{wards:{}}}},document:{getElementById:id=>elements[id],createElement:t=>new Element(t)},location:{href:'https://rochdaledaily.co.uk/my-rochdale',origin:'https://rochdaledaily.co.uk'},fetch:fetcher,URL,AbortController,setTimeout,clearTimeout,console,Intl};
 vm.runInNewContext(fs.readFileSync('assets/js/my-rochdale.js','utf8'),context);
 return {elements,start:async pc=>{elements.postcode.value=pc;await elements.lookup.listeners.submit({preventDefault(){}});}};
}
const stories=[{title:'New mural in Middleton town centre',slug:'middleton-mural',url:'/articles/middleton-mural.html',category:'Community',published_at:'2026-10-13'}, {title:'Rochdale Town Centre update',slug:'rochdale-update',url:'/articles/rochdale-update.html',category:'News',published_at:'2026-10-13'}];
function feeds(url){
 if(url.includes('kind=area'))return {location:{postcode:'OL16 1XU',ward:'Central Rochdale',district:'Rochdale',latitude:53.61,longitude:-2.15}};
 if(url==='/archive-index.json')return stories;
 if(url==='/ward_areas.json')return {wards:{'Central Rochdale':{areas:[]}}};
 if(url==='/articles.json')return [{title:'Dated published event',status:'published',slug:'rochdale-update',event_start_at:'2099-11-07T19:00:00Z',event_location:'Rochdale Town Hall'}];
 if(url==='/api/events')return {events:[]};
 if(url==='/council_votes.json')return {wards:{}};
 if(url.includes('gmp-ward'))return {wards:{}};
 if(url.includes('kind=weather'))return {now:{temperatureC:10,condition:'partlycloudy_day'},days:[]};
 if(url==='/api/traffic')return {disruptions:[]};
 if(url.includes('kind=flood'))return {warningsAvailable:true,warnings:[],stations:[]};
 return {constraints:[]};
}
const fetchOK=async url=>({ok:true,json:async()=>feeds(url)});
test('second postcode lookup recreates controls and excludes generic Middleton town centre match',async()=>{
 const {elements,start}=dashboard(fetchOK);await start('OL16 1XU');assert.equal(elements['news-controls'].querySelectorAll('.tab').length,2);
 assert.ok(elements.stories.textContent.includes('Rochdale Town Centre update'));assert.ok(!elements.stories.textContent.includes('New mural'));
 await start('OL16 1XU');assert.equal(elements['news-controls'].querySelectorAll('.tab').length,2);
 assert.ok(elements.events.textContent.includes('Dated published event'));assert.ok(elements.weather.textContent.includes('Partly cloudy'));
});
test('failed optional ward map does not discard the archive',async()=>{
 const {elements,start}=dashboard(async url=>{if(url==='/ward_areas.json')throw Error('offline');return fetchOK(url);});await start('OL16 1XU');assert.ok(elements.stories.textContent.includes('Rochdale Town Centre update'));
});
test('unavailable data sources finish their briefing state',async()=>{
 const {elements,start}=dashboard(async url=>{if(url==='/api/traffic'||url.includes('kind=flood'))throw Error('offline');return fetchOK(url);});await start('OL16 1XU');assert.ok(!elements['glance-items'].textContent.includes('Checking the source'));assert.match(elements.status.textContent,/Some sources are unavailable/);
});
test('late weather for an older postcode cannot overwrite a completed newer lookup',async()=>{
 let release,count=0;const {elements,start}=dashboard(async url=>{if(url.includes('kind=weather')&&++count===1)return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({now:{temperatureC:99},days:[]})});});return fetchOK(url);});
 const old=start('OL16 1XU');while(!release)await new Promise(resolve=>setImmediate(resolve));await start('OL12 6QY');release();await old;assert.ok(!elements.weather.textContent.includes('99°C'));
});
async function newsletter(){const text=fs.readFileSync('functions/api/newsletter.js','utf8');return import('data:text/javascript;base64,'+Buffer.from(text).toString('base64'));}
function kvStore(){const m=new Map();return {m,get:async(k,o)=>{const s=m.get(k);return o?.type==='json'&&s?JSON.parse(s):s||null;},put:async(k,v)=>m.set(k,v),delete:async k=>m.delete(k),list:async({prefix})=>({keys:[...m.keys()].filter(k=>k.startsWith(prefix)).map(name=>({name})),list_complete:true})};}
const signup=(body)=>new Request('https://rochdaledaily.co.uk/api/newsletter',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
test('newsletter rejects malformed requests, missing consent and oversized email without storing a subscriber',async()=>{
 if(!global.crypto)Object.defineProperty(global,"crypto",{value:webcrypto});const api=await newsletter(),kv=kvStore(),env={EVENTS_KV:kv};
 for(const body of [null,[],{email:'reader@example.com'},{email:'a'.repeat(250)+'@example.com',consent:true}])assert.equal((await api.onRequestPost({request:signup(body),env})).status,400);
 assert.equal(kv.m.size,0);
});
test('newsletter signup is idempotent and honest when delivery is unconfigured; export survives a lost index',async()=>{
 const api=await newsletter(),kv=kvStore(),env={EVENTS_KV:kv,EVENTS_ADMIN_TOKEN:'test-admin',EVENTS_IP_SALT:'test'};
 for(let i=0;i<2;i++){const r=await api.onRequestPost({request:signup({email:'reader@example.com',consent:true,source:'comma,quote"'}),env});assert.equal(r.status,200);assert.match((await r.json()).message,/not being sent yet/);}
 assert.equal([...kv.m.keys()].filter(k=>k.startsWith('newsletter:sub:')).length,1);
 kv.m.set('newsletter:index','[]');
 const request=new Request('https://rochdaledaily.co.uk/api/newsletter?export=csv',{headers:{'x-admin-token':'test-admin'}});
 const response=await api.onRequestGet({request,env});assert.match(await response.text(),/"reader@example.com".*"comma,quote"""/);
 const unauth=await api.onRequestGet({request:new Request(request.url),env});assert.equal(unauth.status,401);
});
