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
const when=s=>{const d=Date.parse(s||"");return Number.isFinite(d)?new Date(d).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}):"";};
const norm=s=>String(s||"").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g," ").replace(/\s+/g," ").trim();
const whole=(t,x)=>x.length>3&&(" "+norm(t)+" ").includes(" "+norm(x)+" ");
const read=async (url,timeout=12000)=>{
 const ctl=new AbortController(),clock=setTimeout(()=>ctl.abort(),timeout);
 try{const response=await fetch(url,{signal:ctl.signal,cache:"no-store",headers:{Accept:"application/json"}});if(!response.ok)throw Error("Source returned "+response.status);const j=await response.json();if(j?.ok===false)throw Error(j.error||"Source unavailable");return j;}
 finally{clearTimeout(clock)}
};
const unavailable=(id,source,msg)=>out(id,[node("p",msg||"This data source is not responding. Its official website has the latest information."),link("Open the official source ↗",source)]);
let archive=[],aliases=[],active="local",category="all",search="",page=0,requestId=0,area={},lastEvents=null,archiveReadyForPostcode=false;
const brief={};
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
  sel.onchange=()=>{category=sel.value;page=0;news();};filters.append(inp,sel);controls.append(tabs,filters);controls.dataset.ready="yes";
 }
 controls.querySelectorAll(".tab").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.view===active)));
 let entries=archive.map(x=>({...x,_match:match(x)})).filter(x=>active==="all"||x._match.score>0);
 // Never backfill local crime from ward-wide or town-wide news reporting.
 if(active==="local")entries=entries.filter(x=>String(x.category||"").toLowerCase()!=="crime"||verifiedNearbyCrime(x,area));
 if(category!=="all")entries=entries.filter(x=>String(x.category).toLowerCase()===category.toLowerCase());
 if(search)entries=entries.filter(x=>norm((x.title||"")+" "+(x.description||"")+" "+x.category).includes(search));
 const recent=(a,b)=>(Date.parse(b.published_at||0)||0)-(Date.parse(a.published_at||0)||0);
 entries.sort((a,b)=>active==="local"?(b._match.score-a._match.score||recent(a,b)):recent(a,b));
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
  const [records,wardData]=await Promise.all([read("/archive-index.json",17000),read("/ward_areas.json",10000)]);
  if(requestId!==id)return;
  archive=Array.isArray(records)?records.filter(x=>x&&x.title&&archiveUrl(x)):[];
  archiveReadyForPostcode=true;
  const config=wardData.wards?.[loc.ward]||{},ward=norm(loc.ward);
  aliases=[...(config.areas||[]).map(x=>String(x).replace(/-/g," ")),loc.ward];
  if(ward.includes("heywood"))aliases.push("Heywood");
  if(ward.includes("middleton"))aliases.push("Middleton");
  if(ward.includes("littleborough"))aliases.push("Littleborough");
  if(ward.includes("milnrow"))aliases.push("Milnrow","Newhey");
  if(ward.includes("central rochdale"))aliases.push("Town Centre","Rochdale Town Hall");
  if(loc.nearbyWhitworth)aliases.push("Whitworth");
  aliases=[...new Set(aliases.map(norm).filter(x=>x.length>3))];
  active="local";category="all";search="";page=0;
  byId("news-controls").replaceChildren();byId("news-controls").dataset.ready="";
  news();
  const localCount=archive.filter(x=>match(x).score>0&&(String(x.category||"").toLowerCase()!=="crime"||verifiedNearbyCrime(x,area))).length;
  putBrief("news",localCount+" articles mention your ward or nearby places, out of "+archive.length+" available archive reports.");
  roadworks();
  if(lastEvents)events(lastEvents);
 }catch{
  archiveReadyForPostcode=false;
  unavailable("stories","/archive.html","Full news archive could not load. Open the archive to search directly.");
 }
}
function roadworks(){
 const matches=archive.filter(x=>/traffic|transport/i.test(x.category)&&/roadwork|road closure|temporary closure|bridge works|road works|lane closure/i.test(x.title+" "+x.description));
 const closer=matches.filter(x=>match(x).score>0),rows=(closer.length?closer:matches).slice(0,10);
 const host=byId("roadworks");host.replaceChildren(list(rows.map(s=>({title:s.title,href:archiveUrl(s),meta:(closer.length?"Local-area article":"Borough report")+" · Published "+when(s.published_at)}))));
 if(!rows.length)host.append(node("p","No roadwork reports available in the searchable archive."));
 host.append(node("p","Articles describe reported works and may not reflect current closures. Check council notices.","method"));
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
async function weatherForPostcode(coords){
 try{preciseWeather(await read("/api/borough-data?kind=weather"+coords,17500));}
 catch(err){
  try{weather(await read("/weather.json"));}
  catch{unavailable("weather","https://www.metoffice.gov.uk/");}
 }
}
function traffic(d,loc){
 const data=Array.isArray(d.disruptions)?d.disruptions:[];
 const nearby=x=>Number.isFinite(x.lat)&&Number.isFinite(x.lon)?Math.sqrt(Math.pow((x.lat-loc.latitude)*111,2)+Math.pow((x.lon-loc.longitude)*66,2)):999;
 const sorted=data.slice().sort((a,b)=>nearby(a)-nearby(b));
 const rows=sorted.slice(0,20).map(x=>({title:String(x.summary||x.description||"Bus disruption").slice(0,180),meta:[nearby(x)<6?"Near this postcode":'Borough-wide notice',x.places?.slice(0,3).join(", "),x.lines?.length?"Services "+x.lines.slice(0,6).join(", "):"",x.end?"Listed until "+when(x.end):""].filter(Boolean).join(" · ")}));
 out("traffic",[node("p",data.length+" bus disruption notices in the borough feed.","news-count"),list(rows),node("p","This feed covers reported bus disruptions, not all road traffic or train cancellations.","method")]);
 putBrief("traffic",data.filter(x=>nearby(x)<6).length+" nearby bus disruption notices; "+data.length+" across the borough.");
}
function events(d){
 lastEvents=d;
 const data=Array.isArray(d.events)?d.events:[];
 const scored=data.slice().sort((a,b)=>{
  const ma=aliases.some(x=>whole(a.event_location+" "+a.title,x)),mb=aliases.some(x=>whole(b.event_location+" "+b.title,x));
  return Number(mb)-Number(ma)||Date.parse(a.event_start_at||0)-Date.parse(b.event_start_at||0);
 });
 const rows=scored.slice(0,20).map(x=>({title:x.title||"Event",href:/^[a-z0-9-]+$/i.test(x.slug||"")?"/articles/"+x.slug+".html":undefined,meta:[when(x.event_start_at),x.event_location,x.event_cost].filter(Boolean).join(" · ")}));
 out("events",[node("p",data.length+" approved upcoming community events.","news-count"),list(rows)]);
 putBrief("events",data.length+" approved upcoming events in Rochdale Daily’s community feed.");
}
function flood(d){
 const result=[],warnings=Array.isArray(d.warnings)?d.warnings:[],stations=Array.isArray(d.stations)?d.stations:[];
 if(!d.warningsAvailable)result.push(node("p","The warning feed could not be checked. Check the official service.","risk"));
 else if(!warnings.length)result.push(node("p","No warnings returned for this vicinity. Do not rely on this page for flood safety."));
 result.push(list(warnings.slice(0,12).map(x=>({title:x.area||"Warning",meta:[x.level,x.message].filter(Boolean).join(" · ")}))));
 if(stations.length)result.push(node("h4","Nearby river measuring stations"));
 result.push(list(stations.slice(0,9).map(x=>({title:x.name||x.station,href:x.url,meta:[x.river,x.reading?.value!=null?"Reading: "+x.reading.value+" (unit depends on station)":"No recent measurement",x.reading?.dateTime?when(x.reading.dateTime):""].filter(Boolean).join(" · ")}))));
 out("flood",result);
 putBrief("flood",!d.warningsAvailable?"Could not check official flood warnings.":warnings.length?warnings.length+" nearby flood alerts or warnings returned.":"No nearby warnings returned by this feed; check the official service.");
}
async function wardPolicingEvidence(expectedWard,expectedRequest){
 const target=byId("crime-local-priorities");if(!target)return;
 target.replaceChildren(node("p","Checking published neighbourhood policing priorities…","loading"));
 try{
  const data=await read("/assets/data/gmp-ward-policing-priorities.json",11000);
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
 out("planning",[node("p",data.length+" data entries returned; some designation datasets may be incomplete.","news-count"),list(data.map(x=>({title:x.name||x.dataset||"Planning designation",meta:[x.dataset,x.reference].filter(Boolean).join(" · ")}))),node("p","No results does not prove that a property has no restrictions.","method")]);
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
 const records=await read("/council_votes.json",11000);
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

function services(loc){
 const rows=[
  ["Your ward and councillors","/wards/"+norm(loc.ward).replace(/\s+/g,"-")+".html","Ward profile"],
  ["Bin collection and recycling","https://www.rochdale.gov.uk/","Find official collection services and schedules"],
  ["School term dates","https://www.rochdale.gov.uk/","Council school term information"],
  ["Council roadworks","https://www.rochdale.gov.uk/directory/22/search-for-roadworks-in-rochdale-borough/category/140","Official roadwork directory"],
  ["Bus and tram travel","https://tfgm.com/","Bee Network updates"],
  ["Live train departures","https://www.nationalrail.co.uk/live-trains/","National Rail running information"],
  ["NHS care near you","https://www.nhs.uk/nhs-services/services-near-you/","Hospitals, GPs, dentists and pharmacies"],
  ["Food hygiene ratings","https://ratings.food.gov.uk/","Restaurants and takeaway inspections"],
  ["Check official flood warnings","https://check-for-flooding.service.gov.uk/","Environment Agency"],
  ["Report a local problem","https://www.fixmystreet.com/","Public-service reports"]
 ];
 if(loc.nearbyWhitworth||!loc.ward)rows.shift();
 out("services",[list(rows.map(x=>({title:x[0],href:x[1],meta:x[2]})))]);
 putBrief("services","Council, bins, schools, trains, NHS and local reporting links.");
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
async function showBoroughIfLookupFails(){
  // A failed postcode resolver must not blank the entire newspaper.
  report("We couldn’t match that postcode just now. Borough-wide news, weather, travel and events are still available.","error");
  byId("ward-councillors").hidden=true;
  byId("crime-local-priorities").replaceChildren(node("p","Your ward must be identified before local GMP priorities can be displayed. Other areas are never substituted.","method"));
  byId("location").hidden=true;byId("lookup").querySelector("button").disabled=false;
   const fallback={district:"Rochdale",ward:"",latitude:53.615,longitude:-2.155};
  await Promise.allSettled([
    (async()=>{await newsArchive(fallback,requestId);active="all";news();})(),
    (async()=>{try{weather(await read("/weather.json"));}catch{unavailable("weather","https://www.metoffice.gov.uk/")}})(),
    (async()=>{try{traffic(await read("/api/traffic"),fallback);}catch{unavailable("traffic","https://tfgm.com/")}})(),
    (async()=>{try{events(await read("/api/events"));}catch{unavailable("events","/whats-on.html")}})()
  ]);
  services(fallback);
  ["flood","planning"].forEach(id=>unavailable(id,errorSources[id],"This source requires a successful postcode lookup. Open the official service."));
}
const errorSources={councillors:"https://democracy.rochdale.gov.uk/mgMemberIndex.aspx?bcr=1",weather:"https://www.metoffice.gov.uk/",traffic:"https://tfgm.com/",events:"/whats-on.html",flood:"https://check-for-flooding.service.gov.uk/",planning:"https://www.planning.data.gov.uk/"};
async function start(e){
 e?.preventDefault();
 const input=byId("postcode").value.trim().toUpperCase();
 if(!/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/.test(input)){report("Enter a full UK postcode, for example OL16 1XU.","error");return;}
 const id=++requestId,button=byId("lookup").querySelector("button");button.disabled=true;
 button.textContent="Finding your area…";
 report("Looking up your postcode and preparing the latest crime reports, weather and news…","loading");
 status.scrollIntoView({behavior:"smooth",block:"center"});
 status.focus({preventScroll:true});
 ["stories","weather","traffic","events","flood","planning","services"].forEach(k=>out(k,[node("p","Checking the source…","loading")]));
 byId("ward-councillors").hidden=true;
 byId("news-controls").replaceChildren();byId("roadworks").replaceChildren();lastEvents=null;
 archive=[];aliases=[];area={};archiveReadyForPostcode=false;
 byId("crime-local-priorities").replaceChildren(node("p","Checking GMP priorities for your ward…","loading"));
 for(const k of Object.keys(brief))delete brief[k];byId("daily-brief").hidden=true;
 try{
  const data=await safePostcodeLookup(input);
  if(id!==requestId)return;
  const loc=data.location;area=loc;
  byId("area-name").textContent=loc.ward||loc.district;
  byId("area-detail").textContent=(loc.nearbyWhitworth?"Whitworth and surrounding communities":"Rochdale borough")+" · Postcode location is approximate.";
  byId("area-postcode").textContent=loc.postcode;
  byId("location").hidden=false;
  byId("glance-area-label").textContent="Your local briefing · "+(loc.ward||loc.district);
  report("✓ "+loc.ward+" found. Your day at a glance is loading below.","success");
  // The first result is the daily briefing. Make it visible immediately,
  // before slower news, transport and official data requests resolve.
  services(loc);
  byId("daily-brief").scrollIntoView({behavior:"smooth",block:"start"});
  if(loc.ward)void wardPolicingEvidence(loc.ward,id);
  const param="&lat="+Number(loc.latitude).toFixed(3)+"&lon="+Number(loc.longitude).toFixed(3);
  const work=[
   ["councillors",()=>councillors(loc,id)],
   ["archive",()=>newsArchive(loc,id)],
   ["weather",()=>weatherForPostcode(param)],
   ["traffic",async()=>traffic(await read("/api/traffic"),loc)],
   ["events",async()=>events(await read("/api/events"))],
   ["flood",async()=>flood(await read("/api/borough-data?kind=flood"+param,19000))],
      ["planning",async()=>planning(await read("/api/borough-data?kind=planning"+param,16000))]
  ];
  await Promise.allSettled(work.map(async x=>{try{await x[1]();}catch(err){if(id===requestId){
      if(x[0]==="councillors"){
       byId("ward-councillors").hidden=false;
       byId("councillor-cards").replaceChildren(node("p","Councillor and voting records could not be loaded. Please consult Rochdale Council's official directory.","method"),
          link("Official councillor directory ↗",errorSources.councillors));
      }else unavailable(x[0]==="archive"?"stories":x[0],errorSources[x[0]]||"/archive.html");
     };}}));
  if(id===requestId)report("✓ Your day at a glance is ready for "+loc.ward+". Councillors, news and GMP priorities are shown next.","success");
 }catch(err){if(id===requestId)await showBoroughIfLookupFails();}
 finally{if(id===requestId){button.disabled=false;button.textContent="Explore my area →";}}
}
byId("lookup").addEventListener("submit",start);
})();