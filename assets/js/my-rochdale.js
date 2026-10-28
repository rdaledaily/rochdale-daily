/* Postcode-first local newspaper and services dashboard.
 * Archive search does not claim GPS-level tagging. All dynamic third-party
 * values are rendered via textContent, never as HTML.
 */
(() => {
"use strict";
const byId=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x;};
const out=(id,nodes)=>{const x=byId(id);if(x)x.replaceChildren(...nodes);};
const link=(text,href)=>{const a=node("a",text);try{const u=new URL(href,location.href);if(u.protocol!=="https:"&&u.origin!==location.origin)throw Error();a.href=u.href;if(u.origin!==location.origin){a.target="_blank";a.rel="noopener noreferrer";}}catch{a.removeAttribute("href");}return a;};
const list=(records)=>{const ul=node("ul",undefined,"data-list");records.forEach(x=>{const li=node("li");li.append(x.href?link(x.title,x.href):node("strong",x.title));if(x.meta)li.append(node("small",x.meta));ul.append(li);});return ul;};
const status=byId("status");
const report=(s,state="ready")=>{status.textContent=s;status.classList.toggle("error",state==="error");status.classList.toggle("loading",state==="loading");status.classList.toggle("success",state==="success");status.setAttribute("aria-busy",String(state==="loading"));};
const when=s=>{const d=Date.parse(s||"");return Number.isFinite(d)?new Date(d).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"Europe/London"}):"";};
const norm=s=>String(s||"").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g," ").replace(/\s+/g," ").trim();
const whole=(t,x)=>x.length>3&&(" "+norm(t)+" ").includes(" "+norm(x)+" ");
const read=async (url,timeout=12000)=>{
 const ctl=new AbortController(),clock=setTimeout(()=>ctl.abort(),timeout);
 try{const response=await fetch(url,{signal:ctl.signal,cache:"no-store",headers:{Accept:"application/json"}});if(!response.ok)throw Error("Source returned "+response.status);const j=await response.json();if(j?.ok===false)throw Error(j.error||"Source unavailable");return j;}
 finally{clearTimeout(clock)}
};
const unavailable=(id,source,msg)=>out(id,[node("p",msg||"This data source is not responding. Its official website has the latest information."),link("Open the official source ↗",source)]);

let snapshotLoad=null;
function savedPublicData(){
 if(window.RD_LOCAL_SNAPSHOT)return Promise.resolve(window.RD_LOCAL_SNAPSHOT);
 if(snapshotLoad)return snapshotLoad;
 snapshotLoad=new Promise((resolve,reject)=>{
   const tag=document.createElement("script");
   tag.src="/assets/data/my-rochdale-snapshot.js";
   tag.async=true;
   const timer=setTimeout(()=>{tag.remove();reject(Error("Saved newsroom data timed out"));},12500);
   tag.onload=()=>{clearTimeout(timer);
     if(window.RD_LOCAL_SNAPSHOT)resolve(window.RD_LOCAL_SNAPSHOT);
     else reject(Error("Saved newsroom data missing"));};
   tag.onerror=()=>{clearTimeout(timer);reject(Error("Saved newsroom script unavailable"));};
   document.head.append(tag);
 });
 return snapshotLoad;
}
async function readOwnData(url,field,timeout=5500){
 try{return await read(url,timeout);}
 catch(err){
   const saved=await savedPublicData();
   if(saved&&saved[field]!=null)return saved[field];
   throw err;
 }
}

let publishedEvents=[],archive=[],aliases=[],active="local",category="all",search="",page=0,requestId=0,area={},lastEvents=null,archiveReadyForPostcode=false;
const brief={};
let newsOrder="recent";
const briefNames=[["news","Your local headlines","#stories"],["weather","Forecast","#weather"],["traffic","Travel today","#traffic"],["events","Coming up","#events"],["flood","River and flood watch","#flood"],["services","Local services","#services"]];
function putBrief(key,value){
 brief[key]=String(value);
 const grid=byId("glance-items");if(!grid)return;grid.replaceChildren();
 for(const [k,title,href] of briefNames){
  const box=node("div",undefined,"glance-item");
  box.append(node("strong",title),node("span",brief[k]||"Checking the source…"));
  box.append(link("See details →",href));grid.append(box);
 }
 byId("daily-brief").hidden=false;
}

const archiveUrl=x=>/^\/articles\/[a-z0-9-]+\.html$/i.test(x.url||"")?x.url:"";
// Crime location protection: a ward/place-name mention is NOT a nearby crime.
// Only show a reported incident when an editor has verified its incident
// coordinates and the point is within one mile of the selected postcode.
// The current archive index has no verified incident coordinates: in that
// case display no list rather than substitute other areas.
const CRIME_RADIUS_KM=1.609344;
function verifiedNearbyCrime(article,postcodeArea){
 if(String(article.category||"").toLowerCase()!=="crime"||!archiveUrl(article))return false;
 if(article.incident_verified!==true)return false;
 const lat=article.incident_latitude,lon=article.incident_longitude;
 if(typeof lat!=="number"||typeof lon!=="number")return false;
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||!Number.isFinite(postcodeArea.latitude)||!Number.isFinite(postcodeArea.longitude))return false;
 if(Math.abs(lat)>90||Math.abs(lon)>180)return false;
 const radians=d=>d*Math.PI/180;
 const dLat=radians(lat-postcodeArea.latitude),dLon=radians(lon-postcodeArea.longitude);
 const h=Math.sin(dLat/2)**2+Math.cos(radians(postcodeArea.latitude))*Math.cos(radians(lat))*Math.sin(dLon/2)**2;
 return 6371*2*Math.atan2(Math.sqrt(h),Math.sqrt(Math.max(0,1-h)))<=CRIME_RADIUS_KM;
}

function match(s){
 const a=norm((s.title||"")+" "+(s.slug||"").replace(/-/g," ")),b=norm(s.description);
 let score=0,matched="";
 aliases.forEach(w=>{if(whole(a,w)&&score<4){score=4;matched=w;}else if(whole(b,w)&&score<2){score=2;matched=w;}});
 return {score,matched};
}
function news(){
 const host=byId("stories");if(!host)return;
 const controls=byId("news-controls");
 if(!controls.dataset.ready){
  const tabs=node("div",undefined,"news-tabs"),filters=node("div",undefined,"news-filters");
  [["local","My neighbourhood"],["all","All borough news"]].forEach(v=>{const b=node("button",v[1],"tab");b.type="button";b.dataset.view=v[0];b.onclick=()=>{active=v[0];page=0;news();};tabs.append(b);});
  const inp=node("input");inp.type="search";inp.placeholder="Search all headlines";inp.setAttribute("aria-label","Find a story");
  inp.oninput=()=>{search=norm(inp.value);page=0;news();};
  const sel=node("select");sel.setAttribute("aria-label","News subject");
  [["all","All subjects"],["News","News"],["Crime","Crime"],["Traffic","Traffic"],["Transport","Transport"],["Politics","Politics"],["Community","Community"],["Events","Events"],["Education","Schools"],["Health","Health"],["Business","Business"],["Sport","Sport"]].forEach(v=>{const op=node("option",v[1]);op.value=v[0];sel.append(op);});
  sel.onchange=()=>{category=sel.value;page=0;news();};
  const order=node("select");order.setAttribute("aria-label","News ordering");
  [["recent","Newest first"],["relevance","Closest place-name match"]].forEach(v=>{const option=node("option",v[1]);option.value=v[0];order.append(option);});
  order.value=newsOrder;order.onchange=()=>{newsOrder=order.value;page=0;news();};
  filters.append(inp,sel,order);controls.append(tabs,filters);controls.dataset.ready="yes";
 }
 controls.querySelectorAll(".tab").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.view===active)));
 let entries=archive.map(x=>({...x,_match:match(x)})).filter(x=>active==="all"||x._match.score>0);
 // Never backfill local crime from ward-wide or town-wide news reporting.
 if(active==="local")entries=entries.filter(x=>String(x.category||"").toLowerCase()!=="crime"||verifiedNearbyCrime(x,area));
 if(category!=="all")entries=entries.filter(x=>String(x.category).toLowerCase()===category.toLowerCase());
 if(search)entries=entries.filter(x=>norm((x.title||"")+" "+(x.description||"")+" "+x.category).includes(search));
 const recent=(a,b)=>(Date.parse(b.published_at||"")||0)-(Date.parse(a.published_at||"")||0);
 // Local eligibility is unchanged; relevance must not bury current reporting.
 entries.sort((a,b)=>newsOrder==="relevance"&&active==="local"?
   (b._match.score-a._match.score||recent(a,b)):(recent(a,b)||b._match.score-a._match.score));
 const shown=entries.slice(0,20*(page+1));
 const ul=list(shown.map(s=>({title:s.title,href:archiveUrl(s),meta:[when(s.published_at),s.category,active==="local"?"Place mention: "+s._match.matched:"Borough archive"].filter(Boolean).join(" · ")})));
 ul.className="story-list";
 const items=[node("p",entries.length.toLocaleString("en-GB")+" matching articles from "+archive.length.toLocaleString("en-GB")+" available archived reports.","news-count"),ul];
 if(entries.length>shown.length){const more=node("button","Load more stories ("+(entries.length-shown.length).toLocaleString("en-GB")+" remaining)","more-button");more.onclick=()=>{page++;news();};items.push(more);}
 if(!entries.length)items.push(node("p","Nothing matched. Try All borough news or remove a filter."));
 out("stories",items);
}
async function newsArchive(loc,id){
 try{
  const [records,wardData]=await Promise.all([readOwnData("/archive-index.json","archive",5500),readOwnData("/ward_areas.json","wards",5000).catch(()=>({wards:{}}))]);
  if(requestId!==id)return;
  archive=Array.isArray(records)?records.filter(x=>x&&x.title&&archiveUrl(x)):[];
  archiveReadyForPostcode=true;
  const config=wardData.wards?.[loc.ward]||{},ward=norm(loc.ward);
  aliases=[...(config.areas||[]).map(x=>String(x).replace(/-/g," ")),loc.ward];
  if(ward.includes("heywood"))aliases.push("Heywood");
  if(ward.includes("middleton"))aliases.push("Middleton");
  if(ward.includes("littleborough"))aliases.push("Littleborough");
  if(ward.includes("milnrow"))aliases.push("Milnrow","Newhey");
  if(ward.includes("central rochdale"))aliases.push("Rochdale Town Centre","Rochdale Town Hall");
  if(loc.nearbyWhitworth)aliases.push("Whitworth");
  aliases.push(...String(loc.ward||"").split(/,|\band\b/i).map(x=>x.trim()).filter(x=>x.length>3&& !/^central rochdale$|^west littleborough$/i.test(x)));
  aliases=[...new Set(aliases.map(norm).filter(x=>x.length>3))];
  active="local";category="all";search="";page=0;newsOrder="recent";
  byId("news-controls").replaceChildren();byId("news-controls").dataset.ready="";
  news();
  const localCount=archive.filter(x=>match(x).score>0&&(String(x.category||"").toLowerCase()!=="crime"||verifiedNearbyCrime(x,area))).length;
  putBrief("news",localCount+" articles mention your ward or nearby places, out of "+archive.length+" available archive reports.");
  roadworks();
  if(lastEvents)events(lastEvents);
 }catch{
  if(requestId!==id)return;
  archiveReadyForPostcode=false;
  putBrief("news","News archive unavailable. Open the full archive directly.");
  unavailable("stories","/archive","Full news archive could not load. Open the archive to search directly.");
 }
}
function roadworks(){
 const source=archive.filter(x=>/traffic|transport/i.test(x.category)&&
   /roadwork|road closure|temporary closure|bridge works|road works|lane closure/i.test(x.title+" "+x.description));
 const local=source.filter(x=>match(x).score>0),rest=source.filter(x=>!local.includes(x));
 const host=byId("roadworks");host.replaceChildren(node("p",local.length+" roadwork reports mention your postcode area's places.","news-count"));
 if(local.length){
  host.append(list(local.slice(0,14).map(s=>({title:s.title,href:archiveUrl(s),
    meta:"Published "+when(s.published_at)+" · Mentioned "+match(s).matched}))));
 }else host.append(node("p","No archived roadworks reports name your selected ward or nearby locality."));
 if(rest.length){
  const details=node("details"),summary=node("summary","Browse "+rest.length+" other borough roadwork articles");
  details.append(summary,list(rest.slice(0,20).map(s=>({title:s.title,href:archiveUrl(s),meta:"Borough article · Published "+when(s.published_at)}))));
  host.append(details);
 }
 host.append(node("p","Archive articles are not live closure notices. Consult the council's roadworks directory for current restrictions.","method"));
}
function weather(w){
 const host=node("div"),updated=Date.parse(w.generated_at||"");
 host.append(node("p","Met Office · "+String(w.location||"Rochdale")+" · Generated "+when(w.generated_at)));
 if(!Number.isFinite(updated)||Date.now()-updated>36*3600000)host.append(node("p","The last available forecast may be stale. See the Met Office for the latest.","risk"));
 const grid=node("div",undefined,"weather-days");
 (w.days||[]).slice(0,7).forEach(d=>{const box=node("div",undefined,"weather-day");box.append(node("strong",d.weekday||when(d.date)),node("span",d.icon||""),node("b",String(d.temperature_c??"—")+"°C"),node("small",d.condition||""));grid.append(box);});
 host.append(grid,node("p","Rochdale-area forecast, not a hyperlocal measurement.","method"));out("weather",[host]);putBrief("weather","Borough-wide forecast shown as local forecast provider is unavailable.");
}
function weatherCode(code){
 const labels={clearsky:"Clear sky",partlycloudy:"Partly cloudy",lightrain:"Light rain",heavyrain:"Heavy rain",rainshowers:"Rain showers",lightrainshowers:"Light rain showers",lightsnow:"Light snow",heavysnow:"Heavy snow"};
 const clean=String(code||"").replace(/_(day|night|polartwilight)$/,"");
 if(labels[clean])return labels[clean];
 const c=String(code||"").replace(/_(day|night|polartwilight)$/,"").replace(/_/g," ");
 return c?c.charAt(0).toUpperCase()+c.slice(1):"Forecast available";
}
function preciseWeather(w){
 const root=node("div");
 root.append(node("p","Forecast for the approximate postcode area · MET Norway","metric-label"));
 const p=w.now||{};
 const today=node("div",undefined,"local-now");
 const temp=p.temperatureC===null||p.temperatureC===undefined?"—":Math.round(p.temperatureC)+"°C";
 today.append(node("strong",temp,"metric"),node("p",weatherCode(p.condition)));
 const facts=node("p",[
  p.windMs!==null&&p.windMs!==undefined?"Wind "+Math.round(p.windMs*3.6)+" km/h":null,
  p.humidity!==null&&p.humidity!==undefined?"Humidity "+p.humidity+"%":null,
  p.precipitationMm!==null&&p.precipitationMm!==undefined?"Rain "+p.precipitationMm+"mm / next "+p.precipitationHours+"h":null
 ].filter(Boolean).join(" · "),"metric-label");
 today.append(facts);root.append(today);
 const grid=node("div",undefined,"weather-days");
 for(const d of (w.days||[]).slice(0,7)){
  const el=node("div",undefined,"weather-day");
  el.append(node("strong",when(d.date)),node("span","◌"),node("b",d.maxTemp!==null?Math.round(d.maxTemp)+"°C":"—"),node("small",d.minTemp!==null?"Low "+Math.round(d.minTemp)+"°C":""),node("small",weatherCode(d.condition)));
  grid.append(el);
 }
 root.append(grid);
 const hourly=node("div");hourly.append(node("h4","Next hours"));
 const listNodes=(w.hourly||[]).slice(0,12).map(h=>{
  const stamp=new Date(h.time).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",timeZone:"Europe/London"});
  return {title:stamp+" · "+(h.temperatureC!=null?Math.round(h.temperatureC)+"°C":"—")+" · "+weatherCode(h.condition),
   meta:[h.windMs!=null?"Wind "+Math.round(h.windMs*3.6)+" km/h":"",h.precipitationMm!=null?"Precipitation "+h.precipitationMm+"mm / "+h.precipitationHours+"h":""].filter(Boolean).join(" · ")};
 });
 hourly.append(list(listNodes));root.append(hourly);
 root.append(node("p","Adapted from MET Norway (CC BY 4.0); model values cover an approximate location and are not exact street-level measurements. Updated "+(when(w.generatedAt)||"date unavailable")+".","method"));
 root.append(link("Forecast source and licence ↗",w.link||"https://api.met.no/"));
 out("weather",[root]);
 putBrief("weather",(p.temperatureC==null?"Forecast available":Math.round(p.temperatureC)+"°C")+" now · "+weatherCode(p.condition)+(p.windMs!=null?" · wind "+Math.round(p.windMs*3.6)+" km/h":""));
}
async function weatherForPostcode(coords,id){
 try{const data=await read("/api/borough-data?kind=weather"+coords,17500);if(id===requestId)preciseWeather(data);}
 catch(err){
  if(id!==requestId)return;
  try{const data=await readOwnData("/weather.json","weather",5500);if(id===requestId)weather(data);}
  catch{if(id===requestId){unavailable("weather","https://www.metoffice.gov.uk/");putBrief("weather","Forecast unavailable. Check the Met Office.");}}
 }
}
function mapAt(lat,lon){
 if(!Number.isFinite(lat)||!Number.isFinite(lon))return "";
 // OpenStreetMap location, not a claim that a road closure lies exactly here.
 return "https://www.openstreetmap.org/?mlat="+lat.toFixed(5)+"&mlon="+lon.toFixed(5)+"#map=16/"+lat.toFixed(5)+"/"+lon.toFixed(5);
}
function travelDistance(loc,x){
 if(!Number.isFinite(x.lat)||!Number.isFinite(x.lon))return null;
 const rad=v=>v*Math.PI/180,dLat=rad(x.lat-loc.latitude),dLon=rad(x.lon-loc.longitude);
 const a=Math.sin(dLat/2)**2+Math.cos(rad(loc.latitude))*Math.cos(rad(x.lat))*Math.sin(dLon/2)**2;
 return 12742*Math.asin(Math.min(1,Math.sqrt(a)));
}
function disruptionRow(x,loc){
 const li=node("li");
 li.append(node("strong",String(x.summary||x.description||"Travel disruption").slice(0,170)));
 const km=travelDistance(loc,x);
 const meta=[km!=null?km.toFixed(1)+" km from postcode (reported coordinate)":"Location not precisely mapped",
   x.lines?.length?"Services "+x.lines.slice(0,6).join(", "):"",
   x.stops?.length?"Stops: "+x.stops.slice(0,3).join(", "):"",
   x.end?"Expected until "+when(x.end):""].filter(Boolean).join(" · ");
 li.append(node("small",meta));
 if(x.description)li.append(node("small",String(x.description).slice(0,460)));
 if(km!=null)li.append(link("View this disruption's reported location on a map ↗",mapAt(x.lat,x.lon)));
 return li;
}
function traffic(d,loc){
 const data=Array.isArray(d.disruptions)?d.disruptions:[];
 const scored=data.map(x=>({...x,_km:travelDistance(loc,x)}));
 const near=scored.filter(x=>x._km!=null&&x._km<=5).sort((a,b)=>a._km-b._km);
 const areaNotMapped=scored.filter(x=>x._km===null&&
   aliases.some(w=>whole([x.summary,x.description,...(x.places||[]),...(x.stops||[])].join(" "),w)));
 const other=scored.filter(x=>!near.includes(x)&&!areaNotMapped.includes(x));
 const detail=node("div"),heading=node("p",near.length+" geolocated disruptions within 5 km of your postcode; "+areaNotMapped.length+" other notices mentioning your area.","news-count");
 const nearUl=node("ul",undefined,"data-list");
 for(const x of [...near,...areaNotMapped])nearUl.append(disruptionRow(x,loc));
 detail.append(heading,nearUl);
 if(!near.length&&!areaNotMapped.length)detail.append(node("p","No local matches in this feed. That does not mean roads or services are disruption-free."));
 if(other.length){
   const more=node("details"),title=node("summary","Show "+other.length+" other Greater Rochdale disruption notices");
   more.append(title);
   const ul=node("ul",undefined,"data-list");
   for(const x of other)ul.append(disruptionRow(x,loc));
   more.append(ul);detail.append(more);
 }
 detail.append(node("p","Map links point to coordinates supplied in a bus-disruption notice. Bus feed only, not a full road or train status check.","method"));
 out("traffic",[detail]);
 putBrief("traffic",(near.length+areaNotMapped.length)+" local bus disruption notices; "+other.length+" elsewhere in the borough.");
}
function eventRow(x,local){
 const li=node("li",undefined,"local-event");
 const title=node("details"),summary=node("summary",String(x.title||"Community event"));
 title.append(summary);
 const content=node("div",undefined,"event-detail");
 const pc=String(x.event_location||"").match(/\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b/i)?.[0]||"";
 content.append(node("p",[when(x.event_start_at),x.event_location,x.event_cost].filter(Boolean).join(" · ")));
 if(x.summary)content.append(node("p",String(x.summary).slice(0,800)));
 if(x.event_start_at)content.append(node("p","Check timings and cancellations with the organiser before travelling.","method"));
 const known=archive.find(a=>String(a.slug)===String(x.slug||""));
 if(known&&archiveUrl(known))content.append(link("Read the event article →",archiveUrl(known)));
 const meta=node("small",(local?"Local place-name match":"Elsewhere in the borough")+(pc?" · Venue "+pc:""));
 li.append(title,meta);title.append(content);
 return li;
}
function events(d){
 lastEvents=d;
 const records=[...(Array.isArray(d.events)?d.events:[]),...publishedEvents];
 const today=new Intl.DateTimeFormat("en-CA",{timeZone:"Europe/London",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
 const seen=new Set();
 const data=records.filter(x=>{
  if(!x||x.draft||x.status&&x.status!=="published")return false;
  const date=Date.parse(x.event_end_at||x.event_start_at||"");
  if(!Number.isFinite(date)||String(x.event_end_at||x.event_start_at).slice(0,10)<today)return false;
  const key=norm(x.title)+"|"+String(x.event_start_at).slice(0,10)+"|"+norm(x.event_location);
  if(seen.has(key))return false;seen.add(key);return true;
 });

 data.sort((a,b)=>Date.parse(a.event_start_at)-Date.parse(b.event_start_at));
 const matches=data.filter(x=>aliases.some(a=>whole(x.event_location+" "+x.title,a)));
 const rest=data.filter(x=>!matches.includes(x));
 const host=node("div");
 host.append(node("p",matches.length+" published or approved events mention your selected area.","news-count"));
 if(matches.length){
  const ul=node("ul",undefined,"data-list");
  matches.forEach(x=>ul.append(eventRow(x,true)));host.append(ul);
 }else host.append(node("p","No upcoming approved submissions currently mention your ward. Widen the search below to browse the borough."));
 if(rest.length){
  const other=node("details"),head=node("summary","Show "+rest.length+" other borough events");
  const ul=node("ul",undefined,"data-list");rest.forEach(x=>ul.append(eventRow(x,false)));
  other.append(head,ul);host.append(other);
 }
 host.append(node("p","Open an event to view its published location and details. Not every approved event has a separate article or independently verified distance.","method"));
 out("events",[host]);
 putBrief("events",matches.length+" local-area upcoming events; "+rest.length+" other borough events.");
}
async function eventsForPostcode(id){
 const results=await Promise.allSettled([read("/api/events"),read("/articles.json",17000)]);
 if(id!==requestId)return;
 publishedEvents=results[1].status==="fulfilled"&&Array.isArray(results[1].value)?results[1].value.filter(x=>x.event_start_at&&x.status==="published"):[];
 if(results.every(x=>x.status==="rejected"))throw Error("Events unavailable");
 events(results[0].status==="fulfilled"?results[0].value:{events:[]});
 if(results.some(x=>x.status==="rejected"))byId("events").append(node("p","One event source could not be checked; this list is incomplete.","method"));

}
function flood(d){
 const warnings=Array.isArray(d.warnings)?d.warnings:[],
       stations=Array.isArray(d.stations)?d.stations:[];
 const result=[];
 const postcodePath=String(area.postcode||"").toLowerCase().trim().replace(/\s+/g,"-");
 const levels=postcodePath?
  "https://check-for-flooding.service.gov.uk/river-and-sea-levels/"+encodeURIComponent(postcodePath):
  "https://check-for-flooding.service.gov.uk/river-and-sea-levels";
 result.push(link("Check official river levels near "+(area.postcode||"your postcode")+" ↗",levels));
 if(!d.warningsAvailable)result.push(node("p","The warning feed could not be checked. Use the official service.","risk"));
 else if(!warnings.length)result.push(node("p","No nearby warnings were returned. This is not a property flood-risk assessment."));
 if(warnings.length){
  const ul=list(warnings.slice(0,12).map(w=>({
    title:w.area||"Flood warning",
    href:/^https:\/\/environment\.data\.gov\.uk\/flood-monitoring\/id\/floods\//.test(w.url||"")?w.url:levels,
    meta:[w.level,w.message].filter(Boolean).join(" · ")
  })));
  result.push(ul);
 }
 if(stations.length)result.push(node("h4","Nearest verified river measurement stations"));
 const rows=stations.slice(0,10).map(x=>({
   title:x.name||x.station,
   href:/^https:\/\/environment\.data\.gov\.uk\/flood-monitoring\/id\/stations\//.test(x.url||"")?x.url:levels,
   meta:[x.distanceKm!=null?x.distanceKm+" km from postcode":"",
     x.river,x.reading?.value!=null?"Latest reading: "+x.reading.value+" (see record for units)":"Measurement not currently supplied",
     x.reading?.dateTime?when(x.reading.dateTime):""].filter(Boolean).join(" · ")
 }));
 result.push(list(rows));
 out("flood",result);
 putBrief("flood",!d.warningsAvailable?"The official warnings feed could not be verified.":
   warnings.length?warnings.length+" nearby flood warnings returned.":"No nearby warnings reported in this feed; see official postcode results.");
}
async function wardPolicingEvidence(expectedWard,expectedRequest){
 const target=byId("crime-local-priorities");if(!target)return;
 target.replaceChildren(node("p","Checking published neighbourhood policing priorities…","loading"));
 try{
  const data=await readOwnData("/assets/data/gmp-ward-policing-priorities.json","policing",5500);
  if(expectedRequest!==requestId||expectedWard!==area.ward)return;
  const record=data.wards?.[expectedWard];
  if(!record){
   target.replaceChildren(
    node("h4","Your local policing team"),
    node("p","A checked neighbourhood-priority summary is not available for this ward. We will not show priorities from another ward."),
    link("Find your team using your postcode ↗","https://www.gmp.police.uk/area/your-area/")
   );
   return;
  }
  if(!record.url?.startsWith("https://www.gmp.police.uk/"))throw Error("Unexpected source");
  const entries=(record.priorities||[]).map(t=>({title:t}));
  target.replaceChildren(
   node("h4","Current GMP priorities: "+record.policeArea),
   list(entries),
   node("p","Official GMP priority update: "+when(record.updated)+" · Source: Greater Manchester Police","method"),
   link("Check your neighbourhood policing team's latest updates ↗",record.url)
  );
 }catch(err){
  if(expectedRequest===requestId){
   target.replaceChildren(node("p","We could not check official ward policing priorities. No alternative neighbourhood information has been substituted.","method"),link("Find your team at GMP ↗","https://www.gmp.police.uk/area/your-area/"));
  }
 }
}

function planning(d){
 const data=Array.isArray(d.constraints)?d.constraints:[];
 const rows=data.map(x=>({title:x.name||x.dataset||"Planning designation",
   href:/^https:\/\/www\.planning\.data\.gov\.uk\/entity\/\d+$/.test(x.url||"")?x.url:"",
   meta:[String(x.dataset||"").replace(/-/g," "),x.reference,"Official record for the approximate postcode location"].filter(Boolean).join(" · ")}));
 const intro=node("p",data.length+" government planning records returned for your approximate postcode coordinates.","news-count");
 const help=node("p","Each record links directly to the source entity. Planning Data does not include every planning application and this is not an official property search.","method");
 out("planning",[intro,list(rows),help]);
}
function councillorCard(person){
 const card=node("article",undefined,"councillor-card");
 card.append(node("h3",person.name||"Councillor"),node("p",person.party||"Party not verified","councillor-party"));
 if(/^https:\/\/democracy\.rochdale\.gov\.uk\/mgUserInfo\.aspx\?UID=\d+$/.test(person.profile_url||"")){
  card.append(link("Official contact details and surgeries ↗",person.profile_url));
 }
 const votes=Array.isArray(person.votes)?person.votes
   .filter(v=>["for","against","abstain"].includes(v.side)&&/^https:\/\/democracy\.rochdale\.gov\.uk\//.test(v.url||""))
   .sort((a,b)=>(Date.parse(b.date)||0)-(Date.parse(a.date)||0)): [];
 if(!votes.length){
  card.append(node("p","No individually attributed vote in the published records currently available.","vote-note"));
  card.append(node("p","This does not mean the councillor never voted, opposed the motion or failed to attend.","vote-note"));
 }else{
  for(const vote of votes.slice(0,6)){
   const label={for:"Voted for",against:"Voted against",abstain:"Abstained"}[vote.side];
   const container=node("div",undefined,"recorded");
   container.append(node("span",label,"vote-result "+vote.side),
    link(vote.title||"Council vote",vote.url),
    node("p",when(vote.date)+" · Official recorded vote","vote-note"));
   if(vote.description)container.append(node("p",vote.description,"vote-note"));
   card.append(container);
  }
 }
 return card;
}
async function councillors(loc,id){
 const section=byId("ward-councillors"),cards=byId("councillor-cards"),meetings=byId("council-meetings");
 if(!section||!cards)return;
 if(loc.nearbyWhitworth){
  section.hidden=false;
  cards.replaceChildren(node("p","Whitworth is represented by Rossendale Borough Council. The Rochdale councillor roster does not apply here."));
  meetings.replaceChildren(link("Find your Rossendale councillors ↗","https://www.rossendale.gov.uk/"));
  return;
 }
 section.hidden=false;
 cards.replaceChildren(node("p","Checking the official councillor and voting records…","loading"));
 const records=await readOwnData("/council_votes.json","councillors",5500);
 if(id!==requestId)return;
 const people=records.wards?.[loc.ward];
 cards.replaceChildren();
 if(!Array.isArray(people)||people.length!==3){
  cards.append(node("p","The councillor roster for this ward could not be verified. Open the council directory to see the current elected members.","method"));
 }else{
  for(const person of people)cards.append(councillorCard(person));
 }
 meetings.replaceChildren();
 const h=node("h3","Council decisions and original records");
 const p=node("p","Not all decisions have individually named voting lists. A council decision is not evidence that all three ward councillors supported it.");
 meetings.append(h,p);
 const ul=list([
   {title:"July 2026 Council: motions, decisions and minutes",href:"https://democracy.rochdale.gov.uk/ieListDocuments.aspx?CId=156&MID=7147",meta:"16 July 2026 · Council decisions; individual votes not inferred"},
   {title:"2026/27 Budget Council: named individual vote",href:"https://democracy.rochdale.gov.uk/mgAi.aspx?ID=50873",meta:"25 February 2026 · Recorded councillor-by-councillor roll call"},
   {title:"Council meeting calendar and published minutes",href:"https://democracy.rochdale.gov.uk/ieListMeetings.aspx?CommitteeId=156",meta:"Latest agendas, minutes and future meetings"}
 ]);
 meetings.append(ul);
}

function serviceCard(title,href,description,postcode,requiresPostcode){
 const li=node("li",undefined,"postcode-service");
 li.append(link(title+" ↗",href));
 li.append(node("small",description));
 if(requiresPostcode&&postcode){
  const info=node("div",undefined,"service-postcode");
  info.append(node("span","Use "+postcode+" when the official service asks for your postcode."));
  const copy=node("button","Copy postcode");copy.type="button";copy.className="copy-postcode";
  copy.setAttribute("aria-label","Copy "+postcode+" for "+title);
  copy.addEventListener("click",async()=>{
    try{
      await navigator.clipboard.writeText(postcode);copy.textContent="Copied ✓";
    }catch{
      // Still leave a selectable postcode for older browsers.
      copy.textContent="Select the postcode shown above";
    }
  });
  info.append(copy);li.append(info);
 }
 return li;
}
function services(loc){
 const pc=String(loc.postcode||"").toUpperCase().trim();
 const floodPath=pc.toLowerCase().replace(/\s+/g,"-");
 const localFlood=floodPath?
  "https://check-for-flooding.service.gov.uk/river-and-sea-levels/"+encodeURIComponent(floodPath):
  "https://check-for-flooding.service.gov.uk/river-and-sea-levels";
 const rows=loc.nearbyWhitworth?[
  ["Your Rossendale council services","https://www.rossendale.gov.uk/","Whitworth falls within Rossendale. Select the service and address on the council website.",false],
  ["Official river levels near "+pc,localFlood,"A postcode-filtered Environment Agency river-level search.",false]
 ]:[
  ["Your councillors for "+loc.ward,"/wards/"+norm(loc.ward).replace(/\s+/g,"-")+".html","Verified council ward page with elected-member details.",false],
  ["Bin calendar for "+pc,"https://www.rochdale.gov.uk/bins-recycling/bins-collected","Opens the council's actual bin collection calendar. Enter the postcode, then select your address for the exact dates.",true],
  ["School dates and half-term","https://www.rochdale.gov.uk/schools/school-terms-holiday-dates-closures/2","2026–27 Rochdale school dates. Each school may have different INSET dates.",false],
  ["Roadworks notices","https://www.rochdale.gov.uk/directory/22/search-for-roadworks-in-rochdale-borough/category/140","Council-maintained roadworks directory; filter by local street. Nearby reports appear above.",false],
  ["River levels near "+pc,localFlood,"Opens an actual postcode-specific official river-level search.",false]
 ];
 rows.push(
  ["Plan a journey from "+pc,"https://tfgm.com/plan-a-journey","Bee Network journey planner. Enter the postcode as your starting point; this dashboard does not submit it without your action.",true],
  ["Find NHS pharmacies around "+pc,"https://www.nhs.uk/service-search/pharmacy/find-a-pharmacy/","Official pharmacy search: enter this postcode to find local pharmacies.",true],
  ["Find NHS hospitals near "+pc,"https://www.nhs.uk/service-search/Hospital","Official hospital locator, based on the postcode you enter.",true],
  ["Report a problem near your home","https://www.fixmystreet.com/","Report a road or street issue. The service must confirm the street or map location.",true],
  ["Local food hygiene ratings","https://ratings.food.gov.uk/","Official premises ratings. Search using your local town or postcode.",true]
 );
 const root=node("div");
 if(pc){
  const intro=node("p","For "+pc+": each link opens the relevant task or location search, not just a council homepage. Where an address is needed, you will still select it on the official service.","news-count");
  root.append(intro);
 }
 const ul=node("ul",undefined,"data-list");
 for(const [title,href,description,copy] of rows){
  if(title.startsWith("Your councillors")&&!loc.ward)continue;
  ul.append(serviceCard(title,href,description,pc,copy));
 }
 root.append(ul);
 out("services",[root]);
 putBrief("services","Direct links for bin collection, ward councillors, postcode river levels, travel, schools and nearby NHS services.");
}
async function safePostcodeLookup(postcode){
  try{return await read("/api/borough-data?kind=area&postcode="+encodeURIComponent(postcode),12000);}
  catch(err){
    // The site edge may transiently block/timeout, while the public,
    // CORS-enabled postcode API is still available directly to the reader.
    const pc=postcode.toUpperCase().replace(/\s+/g,"");
    const direct=await read("https://api.postcodes.io/postcodes/"+encodeURIComponent(pc),12000);
    const row=direct.result||{};
    const district=String(row.admin_district||""),ward=String(row.admin_ward||"");
    const nearby=/whitworth/i.test(ward)&&/rossendale/i.test(district);
    if(district!=="Rochdale"&&!nearby)throw Error("This postcode is outside Rochdale borough and Whitworth.");
    if(!Number.isFinite(row.latitude)||!Number.isFinite(row.longitude))throw Error("Postcode coordinates are unavailable.");
    return {location:{postcode:String(row.postcode||postcode),district,ward,latitude:row.latitude,longitude:row.longitude,nearbyWhitworth:nearby}};
  }
}
async function showBoroughIfLookupFails(id){
  if(id!==requestId)return;
  // A failed postcode resolver must not blank the entire newspaper.
  report("We couldn’t match that postcode just now. Borough-wide news, weather, travel and events are still available.","error");
  byId("ward-councillors").hidden=true;
  byId("glance-area-label").textContent="Borough-wide briefing · postcode not matched";
  byId("crime-local-priorities").replaceChildren(node("p","Your ward must be identified before local GMP priorities can be displayed. Other areas are never substituted.","method"));
  byId("location").hidden=true;byId("lookup").querySelector("button").disabled=false;
   const fallback={district:"Rochdale",ward:"",latitude:53.615,longitude:-2.155};
  await Promise.allSettled([
    (async()=>{await newsArchive(fallback,id);if(id!==requestId)return;active="all";news();putBrief("news","Borough-wide archive; your postcode could not be matched.");})(),
    (async()=>{try{const data=await readOwnData("/weather.json","weather",5500);if(id===requestId)weather(data);}catch{if(id===requestId){unavailable("weather","https://www.metoffice.gov.uk/");putBrief("weather","Forecast unavailable. Check the Met Office.");}}})(),
    (async()=>{try{const data=await read("/api/traffic");if(id===requestId)traffic(data,fallback);}catch{if(id===requestId){unavailable("traffic","https://tfgm.com/");putBrief("traffic","Travel feed unavailable. Check Bee Network.");}}})(),
    (async()=>{try{await eventsForPostcode(id);}catch{if(id===requestId){unavailable("events","/news/events");putBrief("events","Events unavailable. Open What’s On.");}}})()
  ]);
  if(id!==requestId)return;
  services(fallback);
  putBrief("flood","Select a supported postcode to check local flood information.");
  ["flood","planning"].forEach(id=>unavailable(id,errorSources[id],"This source requires a successful postcode lookup. Open the official service."));
}
async function archiveWhenLiveFeedFails(kind,id){
  if(id!==requestId)return;
  let rows=archive;
  if(!rows.length){
    try{rows=(await savedPublicData()).archive||[];}catch{rows=[];}
  }
  if(id!==requestId)return;
  const category=kind==="events"?/events/i:/traffic|transport/i;
  const matches=rows.filter(a=>category.test(String(a.category||""))&&archiveUrl(a)&&
    aliases.some(w=>whole((a.title||"")+" "+(a.description||""),w)));
  const items=matches.slice(0,12).map(a=>({title:a.title,href:archiveUrl(a),
    meta:"Archived report · "+when(a.published_at)+" · Not verified as a current "+(kind==="events"?"event":"road closure")}));
  const intro=node("p",kind==="events"?
    "Upcoming-event data could not be checked. These are older reports that mention your selected area, not confirmed upcoming activities.":
    "Live transport notices could not be checked. These are archived local transport reports, not current disruption alerts.","risk");
  const key=kind==="events"?"events":"traffic";
  if(!items.length)intro.textContent+=" No local archive matches are available either.";
  out(key,[intro,list(items),
    link(kind==="events"?"Browse the full events section →":"Open the official Bee Network journey planner ↗",
      kind==="events"?"/archive":"https://tfgm.com/plan-a-journey")]);
  putBrief(kind==="events"?"events":"traffic","Live "+(kind==="events"?"events":"transport")+" feed unavailable; "+items.length+" locally relevant archived reports available.");
}
function officialFallback(kind,loc){
 const pc=String(loc.postcode||"").trim().toLowerCase().replace(/\s+/g,"-");
 if(kind==="flood"&&pc){
  out("flood",[node("p","Live river readings could not be verified. Check the official postcode search rather than relying on older data.","risk"),
   link("Official river levels around "+loc.postcode+" ↗",
     "https://check-for-flooding.service.gov.uk/river-and-sea-levels/"+encodeURIComponent(pc))]);
  putBrief("flood","Live flood data unavailable; official postcode link provided.");
 }else if(kind==="planning"){
  const coord=Number(loc.latitude).toFixed(3)+", "+Number(loc.longitude).toFixed(3);
  out("planning",[node("p","Live planning designations could not be checked for "+(loc.postcode||"your area")+". Search the government records by location or consult Rochdale Council.","risk"),
   node("p","Approximate location: "+coord,"method"),link("Open government Planning Data ↗","https://www.planning.data.gov.uk/")]);
 }else unavailable(kind,errorSources[kind]||"/");
}

const errorSources={councillors:"https://democracy.rochdale.gov.uk/mgMemberIndex.aspx?bcr=1",weather:"https://www.metoffice.gov.uk/",traffic:"https://tfgm.com/",events:"/news/events",flood:"https://check-for-flooding.service.gov.uk/",planning:"https://www.planning.data.gov.uk/"};
async function start(e){
 e?.preventDefault();
 const input=byId("postcode").value.trim().toUpperCase();
 if(!/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/.test(input)){report("Enter a full UK postcode, for example OL16 1XU.","error");return;}
 const id=++requestId,button=byId("lookup").querySelector("button");button.disabled=true;
 button.textContent="Finding your area…";
 report("Looking up your postcode and preparing local news, GMP priorities and weather…","loading");
 status.scrollIntoView({behavior:"smooth",block:"center"});
 status.focus({preventScroll:true});
 ["stories","weather","traffic","events","flood","planning","services"].forEach(k=>out(k,[node("p","Checking the source…","loading")]));
 byId("ward-councillors").hidden=true;
 byId("news-controls").replaceChildren();byId("news-controls").dataset.ready="";byId("roadworks").replaceChildren();lastEvents=null;publishedEvents=[];
 byId("location").hidden=true;byId("council-meetings").replaceChildren();
 archive=[];aliases=[];area={};archiveReadyForPostcode=false;
 byId("crime-local-priorities").replaceChildren(node("p","Checking GMP priorities for your ward…","loading"));
 for(const k of Object.keys(brief))delete brief[k];byId("daily-brief").hidden=true;
 try{
  const data=await safePostcodeLookup(input);
  if(id!==requestId)return;
  const loc=data.location;area=loc;
  byId("area-name").textContent=loc.ward||loc.district;
  // Remember the WARD (never the postcode) on this device so the homepage can
  // offer "Your area" on the next visit. Nothing leaves the browser.
  try{if(loc.ward)localStorage.setItem("rd_my_ward",JSON.stringify({ward:loc.ward,url:"/wards/"+norm(loc.ward).replace(/\s+/g,"-"),saved:new Date().toISOString().slice(0,10)}));}catch(_){}
  byId("area-detail").textContent=(loc.nearbyWhitworth?"Whitworth and surrounding communities":"Rochdale borough")+" · Postcode location is approximate.";
  byId("area-postcode").textContent=loc.postcode;
  byId("location").hidden=false;
  byId("glance-area-label").textContent="Your local briefing · "+(loc.ward||loc.district);
  report(""+(loc.ward||loc.district)+" found. Your day at a glance is loading below.","success");
  // The first result is the daily briefing. Make it visible immediately,
  // before slower news, transport and official data requests resolve.
  services(loc);
  byId("daily-brief").scrollIntoView({behavior:"smooth",block:"start"});
  if(loc.ward)void wardPolicingEvidence(loc.ward,id);
  const param="&lat="+Number(loc.latitude).toFixed(3)+"&lon="+Number(loc.longitude).toFixed(3);
  const failed=[];
  const work=[
   ["councillors",()=>councillors(loc,id)],
   ["archive",()=>newsArchive(loc,id)],
   ["weather",()=>weatherForPostcode(param,id)],
   ["traffic",async()=>{const data=await read("/api/traffic");if(id===requestId)traffic(data,loc);}],
   ["events",()=>eventsForPostcode(id)],
   ["flood",async()=>{const data=await read("/api/borough-data?kind=flood"+param,19000);if(id===requestId)flood(data);}],
      ["planning",async()=>{const data=await read("/api/borough-data?kind=planning"+param,16000);if(id===requestId)planning(data);}]
  ];
  await Promise.allSettled(work.map(async x=>{try{await x[1]();}catch(err){if(id===requestId){
      failed.push(x[0]);
      const briefKey=x[0]==="archive"?"news":x[0];
      if(briefNames.some(v=>v[0]===briefKey))putBrief(briefKey,"Source unavailable. Open the official service below.");
      if(x[0]==="councillors"){
       byId("ward-councillors").hidden=false;
       byId("councillor-cards").replaceChildren(node("p","Councillor and voting records could not be loaded. Please consult Rochdale Council's official directory.","method"),
          link("Official councillor directory ↗",errorSources.councillors));
      }else if(x[0]==="events"||x[0]==="traffic"){
        await archiveWhenLiveFeedFails(x[0],id);
       }else if(x[0]==="flood"||x[0]==="planning"){
        officialFallback(x[0],loc);
       }else unavailable(x[0]==="archive"?"stories":x[0],errorSources[x[0]]||"/archive");
     };}}));
  if(id===requestId)report("Your briefing is ready for "+(loc.ward||loc.district)+(failed.length?". Some sources are unavailable; their panels explain where to check.":". Councillors, news and GMP priorities are shown next."),failed.length?"ready":"success");
 }catch(err){if(id===requestId)await showBoroughIfLookupFails(id);}
 finally{if(id===requestId){button.disabled=false;button.textContent="Explore my area →";}}
}
byId("lookup").addEventListener("submit",start);
})();
