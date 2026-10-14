'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

// Run the real mobile/desktop prompt code against deterministic article geometry.
function readingPrompt(mobile, href='/articles/next-story.html'){
 const handlers={}, created=[];let scroll=0;
 const title={textContent:'Related local story'},kicker={textContent:'Community'};
 const card={getAttribute:()=>href,querySelector:s=>s==='.rn-title'?title:kicker};
 const article={offsetHeight:4000,getBoundingClientRect:()=>({top:100-scroll,bottom:4100-scroll}),addEventListener(){}};
 const document={visibilityState:'visible',querySelector:s=>s.includes('.rn-card')?card:s==='.read-next'?{}:s==='.article-copy'||s==='.article-main'?article:null,
  getElementById:()=>null,head:{appendChild(){}},body:{appendChild:x=>created.push(x),classList:{add(){}}},addEventListener(){},
  createElement:t=>{const el=new Element(t);el.querySelector=()=>({textContent:''});el.remove=()=>{};return el;}};
 const window={matchMedia:()=>({matches:mobile}),innerHeight:800,innerWidth:mobile?390:1200,get scrollY(){return scroll;},
  addEventListener:(type,fn)=>{handlers[type]=fn;},removeEventListener(){},requestAnimationFrame:fn=>fn(),getSelection:()=>({toString:()=>''})};
 vm.runInNewContext(fs.readFileSync('assets/js/read-next.js','utf8'),{document,window,location:{href:'https://rochdaledaily.co.uk/articles/current',pathname:'/articles/current',origin:'https://rochdaledaily.co.uk'},URL,
  sessionStorage:{getItem:()=>null,setItem(){}},requestAnimationFrame:fn=>fn(),getComputedStyle:()=>({display:'none'})});
 return {created,scroll:value=>{scroll=value;handlers.scroll?.();}};
}
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.hidden=false;this.value='';this.listeners={};this.className='';this.style={};this.classList={toggle:()=>{},add:()=>{},remove:()=>{}};}
 set textContent(v){this.text=String(v);this.children=[];}get textContent(){return (this.text||'')+this.children.map(c=>c.textContent||'').join(' ');}
 append(...c){this.children.push(...c);}replaceChildren(...c){this.text='';this.children=c;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}querySelectorAll(s){const all=this.children.flatMap(c=>[c,...(c.querySelectorAll?.('*')||[])]);return s==='*'?all:all.filter(c=>s==='button'?c.tagName==='BUTTON':s==='select'?c.tagName==='SELECT':s==='.tab'?c.className==='tab':false);}
 addEventListener(t,f){this.listeners[t]=f;}scrollIntoView(){}focus(){}
}
function dashboard(fetcher,options={}){
 const elements={};for(const [,id] of fs.readFileSync('my-rochdale.html','utf8').matchAll(/id="([^"]+)"/g))elements[id]=new Element();
 elements.lookup.append(new Element('button'));
 const context={window:{RD_LOCAL_SNAPSHOT:options.snapshot||{wards:{wards:{}}}},document:{getElementById:id=>elements[id],createElement:t=>new Element(t)},location:{href:'https://rochdaledaily.co.uk/my-rochdale',origin:'https://rochdaledaily.co.uk'},fetch:fetcher,URL,AbortController,setTimeout,clearTimeout,console,Intl};
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

test('My Rochdale internal links and daily briefing anchors have real destinations',()=>{
 const html=fs.readFileSync('my-rochdale.html','utf8');
 for(const [,href] of html.matchAll(/href="(\/[^"?#]*)(?:[?#][^"]*)?"/g)){
  if(href==='/')continue;
  const file=href.slice(1);assert.ok(fs.existsSync(file)||fs.existsSync(file+'.html'),'Missing internal destination: '+href);
 }
 const script=fs.readFileSync('assets/js/my-rochdale.js','utf8');
 for(const [,id] of script.matchAll(/\["(?:news|weather|traffic|events|flood|services)","[^"]+","#([^"]+)"\]/g))assert.ok(html.includes('id="'+id+'"'),'Missing briefing anchor: '+id);
});
test('new story alerts exclude drafts and the current page',()=>{
 const code=fs.readFileSync('assets/js/new-story-alerts.js','utf8');const a=code.indexOf('  function id('),b=code.indexOf('  function save()',a);
 const context=vm.createContext({FRESH_MS:36*3600000,location:{pathname:'/articles/current.html'}});vm.runInContext(code.slice(a,b)+'\nthis.eligible=eligible;',context);
 const now=Date.now(),story={slug:'new-story',title:'Local report',published_at:new Date(now-1000).toISOString(),status:'published'};
 assert.equal(context.eligible(story,now),true);assert.equal(context.eligible({...story,slug:'current'},now),false);
 assert.equal(context.eligible({...story,status:'draft'},now),false);assert.equal(context.eligible({...story,status:'pending'},now),false);
 assert.equal(context.eligible({...story,slug:'../escape'},now),false);
});

test('shared newsletter controller requires consent and suppresses double submissions',async()=>{
 const script=fs.readFileSync('assets/js/menu.js','utf8');const start=script.indexOf('/* Shared newsletter controller'),end=script.indexOf('/* Visible reporting standards',start);
 const form=new Element('form');form.id='rail-newsletter-form';
 const email=new Element('input');email.name='email';email.value='reader@example.com';const button=new Element('button');button.type='submit';form.append(email,button);
 form.querySelector=function(selector){if(selector==='button[type="submit"]')return button;const name=selector.match(/name="([^"]+)"/)?.[1];return this.querySelectorAll('*').find(x=>x.name===name)||null;};
 button.before=(el)=>form.children.splice(form.children.indexOf(button),0,el);form.reset=()=>{email.value='';};
 const status=new Element();let handler,calls=0,release;
 const document={querySelectorAll:()=>[form],getElementById:()=>status,createElement:t=>new Element(t),createTextNode:t=>({textContent:t}),addEventListener:(type,fn,capture)=>{assert.equal(capture,true);handler=fn;}};
 vm.runInNewContext(script.slice(start,end),{document,fetch:async()=>{calls++;return new Promise(resolve=>{release=resolve;});},AbortController,setTimeout,clearTimeout});
 const event={target:form,preventDefault(){},stopImmediatePropagation(){this.stopped=true;}};
 await handler(event);assert.equal(calls,0);assert.match(status.textContent,/tick the box/);assert.ok(event.stopped);
 form.querySelector('[name="consent"]').checked=true;const pending=handler(event);await handler(event);assert.equal(calls,1);assert.equal(button.disabled,true);
 release({ok:true,json:async()=>({ok:true,message:'Saved; email delivery is not configured.'})});await pending;
 assert.equal(button.disabled,false);assert.equal(form.dataset.submitting,undefined);assert.match(status.textContent,/not configured/);
});
test('comment network failures become actionable errors rather than rejected button handlers',async()=>{
 const script=fs.readFileSync('assets/js/article-comments.js','utf8'),start=script.indexOf('  async function api(payload)'),end=script.indexOf('\n  const message=',start);
 const context=vm.createContext({API:'/api/comments',fetch:async()=>{throw Error('network offline');},AbortController,setTimeout,clearTimeout});vm.runInContext(script.slice(start,end)+'\nthis.api=api;',context);
 const result=await context.api({action:'comment'});assert.equal(result.ok,false);assert.match(result.data.error,/Could not connect/);
});

test('comment feed errors never masquerade as an empty discussion',async()=>{
 const script=fs.readFileSync('assets/js/article-comments.js','utf8'),start=script.indexOf('  async function readComments(){'),end=script.indexOf('  let mountVersion=',start);
 async function run(response){const context=vm.createContext({API:'/api/comments',slug:'local-story',session:null,fetch:async()=>response,AbortController,setTimeout,clearTimeout});vm.runInContext(script.slice(start,end)+'\nthis.read=readComments;',context);return context.read();}
 await assert.rejects(run({ok:false,json:async()=>({error:'Unavailable'})}));
 await assert.rejects(run({ok:true,json:async()=>null}));
 await assert.rejects(run({ok:true,json:async()=>({})}));
 assert.equal((await run({ok:true,json:async()=>({closed:false,comments:[]})})).comments.length,0);
 assert.equal((await run({ok:true,json:async()=>({closed:true})})).closed,true);
});

test('off-screen reading prompts are hidden from assistive technology and keyboard navigation',()=>{
 for(const mobile of [true,false]){
  const fixture=readingPrompt(mobile),prompt=fixture.created[0];assert.ok(prompt);
  assert.equal(prompt.style.visibility,'hidden');assert.equal(prompt.attributes['aria-hidden'],'true');
  if(mobile)assert.equal(prompt.tabIndex,-1);else assert.equal(prompt.inert,true);
  fixture.scroll(2200);assert.equal(prompt.style.visibility,'visible');assert.equal(prompt.attributes['aria-hidden'],'false');
  if(mobile)assert.equal(prompt.tabIndex,0);else assert.equal(prompt.inert,false);
  fixture.scroll(0);assert.equal(prompt.style.visibility,'hidden');assert.equal(prompt.attributes['aria-hidden'],'true');
 }
});
test('reading prompts never link back to the current article through its .html alias',()=>{
 for(const mobile of [true,false])assert.equal(readingPrompt(mobile,'/articles/current.html').created.length,0);
});

test('advertiser website entry accepts normal domains without bypassing form or server validation',()=>{
 const html=fs.readFileSync('advertise.html','utf8'),start=html.indexOf(' function normaliseWebsite('),end=html.indexOf(" form.addEventListener('submit'",start);
 const context=vm.createContext({URL});vm.runInContext(html.slice(start,end)+'\nthis.normalise=normaliseWebsite;',context);
 assert.equal(context.normalise(' www.localshop.co.uk '),'https://www.localshop.co.uk/');
 assert.equal(context.normalise('localshop.co.uk/contact'),'https://localshop.co.uk/contact');
 assert.equal(context.normalise('https://localshop.co.uk/'),'https://localshop.co.uk/');
 assert.equal(context.normalise(''),'');
 for(const bad of ['javascript:alert(1)','not a website','user@localshop.co.uk'])assert.equal(context.normalise(bad),bad);
 assert.match(html,/websiteField\.value=normaliseWebsite\(websiteField\.value\);\s*if\(!form\.reportValidity\(\)\)return;/);
});

test('newsletter signup remains successful when the obsolete shared index cannot be written',async()=>{
 const api=await newsletter(),kv=kvStore(),put=kv.put;
 kv.put=async(key,value,options)=>{if(key==='newsletter:index')throw Error('Legacy index write failed');return put(key,value,options);};
 const response=await api.onRequestPost({request:signup({email:'reader@example.com',consent:true}),env:{EVENTS_KV:kv,EVENTS_IP_SALT:'test'}});
 assert.equal(response.status,200);assert.equal((await response.json()).ok,true);
 assert.equal([...kv.m.keys()].filter(k=>k.startsWith('newsletter:sub:')).length,1);
});

test('local headlines default to newest first while optional relevance order preserves crime safeguards',async()=>{
 const records=[
  {title:'Old Rochdale Town Hall report',slug:'old-local',url:'/articles/old-local.html',category:'News',published_at:'2024-01-01'},
  {title:'Latest community report',description:'Rochdale Town Hall is the venue.',slug:'recent-local',url:'/articles/recent-local.html',category:'Community',published_at:'2026-10-14'},
  {title:'Rochdale Town Hall crime allegation',slug:'unverified-crime',url:'/articles/unverified-crime.html',category:'Crime',published_at:'2026-10-15'}
 ];
 const {elements,start}=dashboard(async url=>url==='/archive-index.json'?{ok:true,json:async()=>records}:fetchOK(url));
 await start('OL16 1XU');
 const rendered=elements.stories.textContent;
 assert.ok(rendered.indexOf('Latest community report')<rendered.indexOf('Old Rochdale Town Hall report'),'Recent local reporting must not be buried under an older title match');
 assert.ok(!rendered.includes('crime allegation'));
 const selects=elements['news-controls'].querySelectorAll('select'),order=selects.find(x=>x.attributes['aria-label']==='News ordering');
 assert.ok(order);order.value='relevance';order.onchange();
 assert.ok(elements.stories.textContent.indexOf('Old Rochdale Town Hall report')<elements.stories.textContent.indexOf('Latest community report'));
 assert.ok(!elements.stories.textContent.includes('crime allegation'));
 await start('OL16 1XU');assert.ok(elements.stories.textContent.indexOf('Latest community report')<elements.stories.textContent.indexOf('Old Rochdale Town Hall report'));
});

test('late archived travel fallback cannot overwrite a newer postcode briefing',async()=>{
 let release,archives=0,traffic=0;
 const snapshot={then(resolve){release=()=>resolve({archive:[{title:'Old transport fallback for Rochdale Town Hall',description:'Archived notice',slug:'old-travel',url:'/articles/old-travel.html',category:'Transport',published_at:'2024-01-01'}]});}};
 const {elements,start}=dashboard(async url=>{
  if(url==='/archive-index.json')return {ok:true,json:async()=>++archives===1?[]:stories};
  if(url==='/api/traffic'&&++traffic===1)throw Error('old request failed');
  return fetchOK(url);
 },{snapshot});
 const old=start('OL16 1XU');while(!release)await new Promise(resolve=>setImmediate(resolve));
 await start('OL16 1XU');const latest=elements.traffic.textContent;release();await old;
 assert.equal(elements.traffic.textContent,latest,'An obsolete archived fallback must not replace current travel results');
 assert.ok(!elements['glance-items'].textContent.includes('locally relevant archived reports'));
});

test('local briefing dates use UK time rather than the device timezone',()=>{
 const script=fs.readFileSync('assets/js/my-rochdale.js','utf8'),start=script.indexOf('const when='),end=script.indexOf('\nconst norm=',start);
 let zone;
 class CapturedDate extends Date {toLocaleDateString(locale,options){zone=options.timeZone;return super.toLocaleDateString(locale,options);}}
 const context=vm.createContext({Date:CapturedDate});vm.runInContext(script.slice(start,end)+'\nthis.when=when;',context);
 assert.equal(context.when('2024-01-01'),'1 Jan 2024');assert.equal(zone,'Europe/London');
 assert.equal(context.when(''),'');
});
