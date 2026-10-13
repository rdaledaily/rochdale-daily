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
const CATEGORIES=new Set(['all','flood','crime','planning','area','contracts','companies','weather']);
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
  // After one postcode lookup, request other feeds by an approximate (~100m)
  // coordinate. Avoid repeated third-party postcode calls and full postcodes
  // appearing in weather, flood, planning or police lookup URLs.
  const a=query.get('lat'),b=query.get('lon');
  if(a!==null&&b!==null&&/^-?\d{1,3}(?:\.\d{1,4})?$/.test(a)&&/^-?\d{1,3}(?:\.\d{1,4})?$/.test(b)){
    const lat=Number(a),lon=Number(b);
    if(lat>=53.44&&lat<=53.80&&lon>=-2.55&&lon<=-1.94)
      return {latitude:lat,longitude:lon,ward:'Rochdale area',district:'Rochdale',isApproximate:true};
    return {error:'Location outside the supported area.'};
  }
  if(!query.get('postcode'))return {latitude:53.615,longitude:-2.155,ward:'Rochdale',district:'Rochdale',isApproximate:true};
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
  // The reader-facing dashboard searches the entire published archive itself.
  // Do not fetch our own origin's /articles.json from within a Pages Function:
  // same-zone fetches can fail even when the site is working for browsers.
  return {ok:true,kind:'area',location:loc,source:'Postcodes.io',link:'https://postcodes.io/',
    archive:'/archive-index.json',wardMap:'/ward_areas.json'};
}
async function localWeather(loc){
  // Approximate location rounded to the nearest ~1km for provider caching
  // and to avoid disclosing the user's full postcode to the forecast supplier.
  const lat=Number(loc.latitude.toFixed(2)),lon=Number(loc.longitude.toFixed(2));
  const u='https://api.met.no/weatherapi/locationforecast/2.0/compact?'+new URLSearchParams({lat:String(lat),lon:String(lon)});
  const d=await jsonGet(u,{ttl:3600,headers:{'User-Agent':'RochdaleDaily/1.0 (https://rochdaledaily.co.uk/contact.html)'}});
  const timeSeries=Array.isArray(d?.properties?.timeseries)?d.properties.timeseries:[];
  if(timeSeries.length===0)throw Error('No forecast periods returned');
  const londonDate=t=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t));
  const now=Date.now();
  const forecast=timeSeries.map(x=>{
    const inst=x.data?.instant?.details||{};
    const near=x.data?.next_1_hours||x.data?.next_6_hours||{};
    return {
      time:tidy(x.time,40),
      temperatureC:Number.isFinite(inst.air_temperature)?inst.air_temperature:null,
      windMs:Number.isFinite(inst.wind_speed)?inst.wind_speed:null,
      humidity:Number.isFinite(inst.relative_humidity)?inst.relative_humidity:null,
      precipitationMm:Number.isFinite(near.details?.precipitation_amount)?near.details.precipitation_amount:null,
      precipitationHours:x.data?.next_1_hours?1:x.data?.next_6_hours?6:null,
      condition:tidy(near.summary?.symbol_code,40)
    };
  }).filter(x=>Date.parse(x.time)>=now-3600000);
  const daily=new Map();
  for(const p of forecast){
    const day=londonDate(p.time);
    if(!daily.has(day))daily.set(day,{date:day,minTemp:null,maxTemp:null,condition:'',hourlyPoints:0});
    const a=daily.get(day);a.hourlyPoints++;
    if(p.temperatureC!==null){a.minTemp=a.minTemp===null?p.temperatureC:Math.min(a.minTemp,p.temperatureC);a.maxTemp=a.maxTemp===null?p.temperatureC:Math.max(a.maxTemp,p.temperatureC)}
    if(!a.condition&&p.condition)a.condition=p.condition;
  }
  return {
    ok:true,kind:'weather',location:loc,generatedAt:tidy(d.properties?.meta?.updated_at,40),
    now:forecast[0]||null,hourly:forecast.slice(0,24),
    days:[...daily.values()].slice(0,7),
    source:'MET Norway Locationforecast 2.0',
    link:'https://api.met.no/weatherapi/locationforecast/2.0/documentation',
    licence:'https://creativecommons.org/licenses/by/4.0/',
    disclaimer:'Approximate postcode-area model forecast. Temperatures, wind and rain can differ by street, elevation and timing. Compiled and rounded by Rochdale Daily from MET Norway data under CC BY 4.0.'
  };
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
  // Important documented force-level absence: GMP has supplied no street-level
  // data to Police.uk since July 2019 (GMP FOI 26.016219/I, January 2026).
  // The national "latest month" MUST NOT be labelled Rochdale data.
  // We intentionally do not count reports from other forces' anonymised map
  // points near Rochdale as GMP incidents.
  return {
    ok:true,kind:'crime',location:loc,month:null,dataAvailable:false,
    localStatisticsAvailable:false,force:'Greater Manchester Police',
    boroughComparison:{
      area:'Rochdale',periodEnd:'2026-03',crimesPer1000:112.00,
      greaterManchesterPer1000:110.96,
      source:'Police.uk Compare your area · ONS recorded crime statistics',
      url:'https://www.police.uk/pu/your-area/greater-manchester-police/performance/compare-your-area/?tc=PC20',
      note:'Rolling 12-month recorded crime rate per 1,000 residents, year ending March 2026. Borough-wide historical comparison, not current crime, ward rate or postcode count. Snapshot checked October 2026.'
    },
    recentCrimeReporting:'/archive.html',
    gmpNews:'https://www.gmp.police.uk/news/news-search/',
    officialStatistics:'https://www.gmp.police.uk/police-forces/greater-manchester-police/areas/greater-manchester-force-content/sd/stats-and-data/',
    source:'GMP disclosure and Police.uk data availability',
    sourceLinks:[
      'https://www.gmp.police.uk/SysSiteAssets/foi-media/greater-manchester/disclosure-2026/april/foi-26.016219.i-historical-street-level-crime--stop-search-data-for-years-2023-2024--2025.pdf',
      'https://data.police.uk/changelog/'
    ],
    disclaimer:'GMP has not provided Police.uk street-level crime data since July 2019. No reliable recent postcode crime count or crime rate can be calculated from that dataset. Recent dated news reports are separate from official statistical totals.'
  };
}
async function planningInfo(loc){
 const p=new URLSearchParams({latitude:String(loc.latitude),longitude:String(loc.longitude),limit:'60'});
 for(const d of ['conservation-area','listed-building','green-belt','article-4-direction-area','tree-preservation-zone','flood-risk-zone'])p.append('dataset',d);
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
   if(kind==='weather')response=await localWeather(loc);
   if(kind==='crime')response=await crimeInfo(loc,u.searchParams)
   if(kind==='planning')response=await planningInfo(loc);
   return reply(response);
 }catch(e){return reply(sourceError(kind,e),503)}
}
