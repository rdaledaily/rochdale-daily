/**
 * Rochdale Daily Borough Data. Public, read-only, geolocated open data.
 * This handler does not write submitted postcodes to KV or analytics.
 * Postcodes appear transiently in request URLs and upstream postcode lookups.
 * Research-only procurement and company search requires existing editor token.
 * Never represents official safety alerts, indexed crime coordinates or
 * incomplete contract search results as exhaustive.
 */
const ORIGIN='https://rochdaledaily.co.uk';
const EA='https://environment.data.gov.uk/flood-monitoring';
const JSON_HEADERS={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'};
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:JSON_HEADERS});
const admin=(r,env)=>Boolean(env.EVENTS_ADMIN_TOKEN&&r.headers.get('x-admin-token')===env.EVENTS_ADMIN_TOKEN);
const tidy=(value,max=80)=>String(value||'').trim().slice(0,max);
const limited=(n,min,max)=>Math.max(min,Math.min(max,n));
const CATEGORIES=new Set(['all','flood','crime','planning','area','contracts','companies']);
async function jsonGet(url,options={}){
  const timer=new AbortController();const abort=setTimeout(()=>timer.abort(),7000);
  try{
    const r=await fetch(url,{method:'GET',signal:timer.signal,headers:{Accept:'application/json',...(options.headers||{})},
      cf:{cacheTtl:options.ttl||300,cacheEverything:true}});
    if(!r.ok)throw new Error('Source returned HTTP '+r.status);
    const raw=await r.text();if(raw.length>1300000)throw new Error('Source response too large');
    return JSON.parse(raw);
  }finally{clearTimeout(abort)}
}
function sourceError(label,err){
  return {ok:false,source:label,error:'The source is temporarily unavailable. Use its official website.',detail:String(err.message||'').slice(0,80)};
}
function homeMatch(s,place,ward){
  const category=String(s.category||'').toLowerCase();
  const text=[s.area,s.location,s.ward,s.title,s.summary].filter(Boolean).join(' ').toLowerCase();
  const aliases=[ward,place].filter(Boolean).map(s=>s.toLowerCase());
  return category!=='crime' && aliases.some(x=>x.length>4 && text.includes(x));
}
function storyURL(slug){
  return /^[a-z0-9][a-z0-9-]{0,160}$/i.test(slug) ? '/articles/'+slug+'.html' : '';
}
async function resolvePostcode(value){
  const pc=tidy(value,12).toUpperCase().replace(/\s+/g,'');
  if(!/^[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}$/.test(pc))return {error:'Enter a complete UK postcode.'};
  const d=await jsonGet('https://api.postcodes.io/postcodes/'+encodeURIComponent(pc),{ttl:86400});
  const item=d?.result;if(!item||d.status!==200)return {error:'Postcode not found.'};
  const district=tidy(item.admin_district,80),ward=tidy(item.admin_ward,80);
  const nearbyWhitworth=/whitworth/i.test(ward)&&/rossendale/i.test(district);
  if(district!=='Rochdale'&&!nearbyWhitworth)return {error:'Our local dashboard currently covers Rochdale borough and Whitworth.'};
  return {postcode:tidy(item.postcode,12),district,ward,parish:tidy(item.parish,80),
    latitude:Number(item.latitude),longitude:Number(item.longitude),nearbyWhitworth};
}
async function position(query){
  if(!query.get('postcode')) return {latitude:53.615,longitude:-2.155,ward:'Rochdale',district:'Rochdale',isApproximate:true};
  return resolvePostcode(query.get('postcode'));
}
function coordParams(loc){return 'lat='+encodeURIComponent(loc.latitude)+'&long='+encodeURIComponent(loc.longitude)+'&dist=10';}
function categories(records){
  const counts=new Map();
  for(const r of records)counts.set(r.category||'other',1+(counts.get(r.category||'other')||0));
  return [...counts].map(([category,count])=>({category,count})).sort((a,b)=>b.count-a.count);
}
function safeHref(href,domain){
  try{const u=new URL(href);return u.protocol==='https:'&&u.hostname===domain?u.toString():''}catch{return ''}
}
async function areaInfo(loc){
  const result={ok:true,kind:'area',location:loc,source:'Postcodes.io',link:'https://postcodes.io/'};
  try {
    const d=await jsonGet(ORIGIN+'/articles.json',{ttl:90});
    const articles=Array.isArray(d)?d:(Array.isArray(d.articles)?d.articles:[]);
    result.stories=articles.filter(s=>homeMatch(s,loc.district==='Rochdale'?'Rochdale': 'Whitworth',loc.ward))
      .slice(0,8).map(s=>({title:tidy(s.title,200),url:storyURL(String(s.slug||'')),area:tidy(s.area,80)}))
      .filter(s=>s.url);
  }catch{result.stories=[];result.storyStatus='News feed temporarily unavailable';}
  return result;
}
async function floodInfo(loc){
  const [warnings,stations]=await Promise.allSettled([
    jsonGet(EA+'/id/floods?'+coordParams(loc)+'&_limit=30',{ttl:120}),
    jsonGet(EA+'/id/stations?'+coordParams(loc)+'&parameter=level&_limit=80',{ttl:600})
  ]);
  if(warnings.status==='rejected'&&stations.status==='rejected')throw Error('Flood monitoring unavailable');
  const floods=warnings.status==='fulfilled'&&Array.isArray(warnings.value.items)?warnings.value.items:[];
  const gauges=stations.status==='fulfilled'&&Array.isArray(stations.value.items)?stations.value.items:[];
  const nearby=gauges.filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.long))).slice(0,12);
  const readings=await Promise.allSettled(nearby.slice(0,4).map(async station=>{
    const stationRef=tidy(station.stationReference,60);
    if(!/^[a-zA-Z0-9_-]{1,60}$/.test(stationRef))return null;
    const d=await jsonGet(EA+'/id/stations/'+encodeURIComponent(stationRef)+'/readings?latest',{ttl:600});
    const r=Array.isArray(d.items)?d.items:[];
    const level=r.find(x=>Number.isFinite(Number(x.value)));
    return level?{station:stationRef,value:Number(level.value),dateTime:tidy(level.dateTime,50),measure:tidy(level.measure,250)}:null;
  }));
  const levelByRef=new Map(readings.filter(x=>x.status==='fulfilled'&&x.value).map(x=>[x.value.station,x.value]));
  return {ok:true,kind:'flood',location:loc,
    warnings:floods.slice(0,20).map(f=>({
      area:tidy(f.description||f.floodArea?.label||'Area warning',180),
      severity:Number(f.severityLevel)||null,level:tidy(f.severity,90),
      message:tidy(f.message,300),changed:tidy(f.timeMessageChanged||f.timeRaised,50)
    })),
    stations:nearby.map(x=>({
      name:tidy(x.label,120),river:tidy(x.riverName,80),station:tidy(x.stationReference,60),
      source:'Environment Agency',url:safeHref(x['@id'],'environment.data.gov.uk'),
      reading:levelByRef.get(tidy(x.stationReference,60))||null
    })),
    warningsAvailable:warnings.status==='fulfilled',stationsAvailable:stations.status==='fulfilled',
    source:'Environment Agency flood-monitoring API (Beta)',link:'https://check-for-flooding.service.gov.uk/',
    disclaimer:'Nearby monitoring locations are not a flood prediction; check official flood warnings before travel.'
  };
}
async function crimeInfo(loc,query){
  const p=new URLSearchParams({lat:String(loc.latitude),lng:String(loc.longitude)});
  const date=tidy(query.get('date')||'',7);
  if(/^\d{4}-(0[1-9]|1[0-2])$/.test(date))p.set('date',date);
  const rows=await jsonGet('https://data.police.uk/api/crimes-street/all-crime?'+p.toString(),{ttl:86400});
  if(!Array.isArray(rows))throw Error('Unexpected police data response');
  return {ok:true,kind:'crime',location:loc,month:tidy(rows[0]?.month||date||'Latest available',30),
    total:rows.length,byCategory:categories(rows),
    radius:'Approximately 1 mile around the postcode coordinate, not the entire ward',
    source:'Police.uk open data',link:'https://data.police.uk/',
    disclaimer:'Monthly historical police-recorded reports, not live incidents. Locations are anonymised. Counts can change and do not identify addresses or individuals.'};
}
async function planningInfo(loc){
 const p=new URLSearchParams({latitude:String(loc.latitude),longitude:String(loc.longitude),limit:'60'});
 for(const d of ['conservation-area','listed-building','green-belt','article-4-direction-area','tree-preservation-zone'])p.append('dataset',d);
 const raw=await jsonGet('https://www.planning.data.gov.uk/entity.json?'+p.toString(),{ttl:3600});
 const rows=Array.isArray(raw.entities)?raw.entities:[];
 return {ok:true,kind:'planning',location:loc,totalReturned:rows.length,
   constraints:rows.slice(0,40).map(x=>({name:tidy(x.name||x.reference||x.dataset,150),dataset:tidy(x.dataset,80),reference:tidy(x.reference,60)})),
   source:'Planning Data (MHCLG)',link:'https://www.planning.data.gov.uk/',
   disclaimer:'Constraints at the approximate postcode coordinate, not an authoritative property search. Dataset coverage varies; no result does not mean no restriction.'};
}
async function contractsResearch(){
 // Capped, intentionally incomplete recent release sample for an editor.
 // Future production investigation should use a scheduled full cursor crawl.
 const from=new Date(Date.now()-7*86400000).toISOString().slice(0,19);
 const until=new Date().toISOString().slice(0,19);
 const u='https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?'+new URLSearchParams({updatedFrom:from,updatedTo:until,limit:'100'});
 const result=await jsonGet(u,{ttl:1800});
 const releases=Array.isArray(result.releases)?result.releases:[];
 const relevant=releases.filter(r=>{
   const buyers=Array.isArray(r.buyer)?r.buyer:[r.buyer||{}];
   return buyers.some(b=>/rochdale/i.test(String(b?.name||'')));
 }).slice(0,30);
 return {ok:true,kind:'contracts',partial:true,updatedFrom:from,updatedTo:until,
   inspected:releases.length,nextPageAvailable:Boolean(result.links?.next),
   matches:relevant.map(x=>({title:tidy(x.tender?.title||x.tag?.join(' / ')||'Procurement notice',180),
     buyer:tidy(x.buyer?.name,120),ocid:tidy(x.ocid,130),date:tidy(x.date,40)})),
   source:'Find a Tender OCDS releases (first page only)',
   link:'https://www.find-tender.service.gov.uk/',
   disclaimer:'Research leads only. First page of a seven-day window is NOT a complete contract register; verify notices and entities before reporting.'};
}
async function companyResearch(query,env){
 const key=String(env.COMPANIES_HOUSE_API_KEY||'');
 if(!key)return {ok:false,kind:'companies',needsSetup:'COMPANIES_HOUSE_API_KEY',error:'Companies House search is waiting for an API key configured in Cloudflare.'};
 const q=tidy(query.get('q'),110);
 if(q.length<3)return {ok:false,error:'Enter at least 3 characters of a company name.'};
 const u='https://api.company-information.service.gov.uk/search/companies?'+new URLSearchParams({q,items_per_page:'15'});
 const d=await jsonGet(u,{ttl:600,headers:{Authorization:'Basic '+btoa(key+':')}});
 return {ok:true,kind:'companies',q,results:(Array.isArray(d.items)?d.items:[]).slice(0,15).map(x=>({
   title:tidy(x.title,160),number:tidy(x.company_number,20),
   status:tidy(x.company_status,40),incorporated:tidy(x.date_of_creation,25),
   address:tidy(x.address_snippet,200),url:/^[A-Z0-9]{5,12}$/i.test(x.company_number||'')?'https://find-and-update.company-information.service.gov.uk/company/'+x.company_number:''
 })),source:'Companies House public register',link:'https://find-and-update.company-information.service.gov.uk/',
 disclaimer:'Search matches may be outside Rochdale. Registered addresses and company links are not evidence of misconduct.'};
}
export async function onRequestGet({request,env}){
 const u=new URL(request.url);const kind=tidy(u.searchParams.get('kind')||'area',24);
 if(!CATEGORIES.has(kind))return reply({ok:false,error:'Unsupported data feed'},400);
 if((kind==='companies'||kind==='contracts')&&!admin(request,env))return reply({ok:false,error:'Editor authorisation required'},401);
 if(kind==='companies'){try{return reply(await companyResearch(u.searchParams,env))}catch(e){return reply(sourceError('Companies House',e),503)}}
 if(kind==='contracts'){try{return reply(await contractsResearch())}catch(e){return reply(sourceError('Find a Tender',e),503)}}
 let loc;
 try{loc=await position(u.searchParams)}catch{return reply({ok:false,error:'Postcode lookup is temporarily unavailable.'},503)}
 if(loc.error)return reply({ok:false,error:loc.error},400);
 if(!Number.isFinite(loc.latitude)||!Number.isFinite(loc.longitude))return reply({ok:false,error:'No coordinates available for this postcode.'},400);
 // Pass explicit query context, never cache or persist a submitted postcode.
 try{
   let response;
   if(kind==='area'||kind==='all')response=await areaInfo(loc);
   if(kind==='flood')response=await floodInfo(loc);
   if(kind==='crime')response=await crimeInfo(loc,u.searchParams)
   if(kind==='planning')response=await planningInfo(loc);
   return reply(response);
 }catch(e){return reply(sourceError(kind,e),503)}
}
