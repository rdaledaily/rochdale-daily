/* Postcode-first local newspaper and services dashboard.
 * Archive search does not claim GPS-level tagging. All dynamic third-party
 * values are rendered via textContent, never as HTML.
 */
(() => {
"use strict";
const byId=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x;};
const out=(id,nodes)=>{const x=byId(id);if(x)x.replaceChildren(...nodes);};
const link=(text,href)=>{const a=node("a",text);try{const u=new URL(href,location.origin);if(u.protocol!=="https:"&&u.origin!==location.origin)throw Error();a.href=u.href;if(u.origin!==location.origin){a.target="_blank";a.rel="noopener noreferrer";}}catch{a.removeAttribute("href");}return a;};
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
  const localCount=archive.filter(x=>match(x).score>0).length;
  putBrief("news",localCount+" articles mention your ward or nearby places, out of "+archive.length+" available archive reports.");
  roadworks();
  recentCrimeReports();
  if(lastEvents)events(lastEvents);
 }catch{
  archiveReadyForPostcode=false;
  unavailable("stories","/archive.html","Full news archive could not load. Open the archive to search directly.");
  const crimeLatest=byId("crime-latest");if(crimeLatest)crimeLatest.replaceChildren(node("p","Local crime coverage could not be checked because the article archive is unavailable. No other-area crimes will be substituted.","method"));
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
function recentCrimeReports(){
 const el=byId("crime-latest");if(!el)return;
 el.replaceChildren();
 // Archive indexing is asynchronous. Never reuse stories left over from a
 // previous postcode while the new ward/area lookup is in progress.
 if(!archiveReadyForPostcode||!area.ward){
  el.append(node("p","Checking for published reports mentioning your neighbourhood…","loading"));
  return;
 }
 const cutoff=Date.now()-90*86400000;
 const recent=archive.filter(x=>{
  if(String(x.category||"").toLowerCase()!=="crime"||!archiveUrl(x))return false;
  const published=Date.parse(x.published_at||"");
  return Number.isFinite(published)&&published>=cutoff;
 }).sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0));
 // Strictly local, with no fallback to unrelated articles elsewhere.
 // Matches are place-name references, NOT a proof of exact postcode distance.
 const local=recent.filter(x=>match(x).score>0);
 el.append(node("h4","Recently published crime and courts reporting"));
 if(!local.length){
  el.append(node("p","No recent Rochdale Daily crime reports specifically mention "+area.ward+" or its mapped neighbourhoods in the last 90 days.","news-count"));
  el.append(node("p","This does not mean no crimes have occurred nearby. Article place-name matching cannot verify distance from an individual postcode, and GMP does not currently provide reliable postcode-level incident data.","method"));
  return;
 }
 el.append(node("p",local.length+" recent reports mention "+area.ward+" or mapped neighbourhoods. These are location mentions, not verified incident distances.","news-count"));
 el.append(list(local.slice(0,16).map(x=>({
  title:x.title,href:archiveUrl(x),
  meta:[when(x.published_at),"Mentions "+match(x).matched,x.category].filter(Boolean).join(" · ")
 }))));
 if(local.length>16)el.append(node("p",String(local.length-16)+" further matching reports can be found in the news archive.","method"));
 el.append(node("p","Dated reporting, not a complete or live police incident list. An article's area mention is not evidence that its event happened within a fixed distance of your postcode.","method"));
}

function crime(d){
 const introduction=node("p","Greater Manchester Police has not supplied street-level crime data to Police.uk since July 2019. Consequently, a reliable recent postcode crime rate or total cannot be calculated from that service.","risk");
 const more=node("p","The Police.uk national 'latest month' does not mean there are up-to-date GMP street-crime records for Rochdale. GMP publishes its own neighbourhood crime data through 2026; those are aggregated counts, not geolocated individual incidents.","method");
 const sources=node("div");
 const comparison=d.boroughComparison;
 const blocks=[introduction];
 if(comparison&&comparison.area==="Rochdale"&&comparison.periodEnd==="2026-03"){
   const card=node("div",undefined,"crime-comparison");
   card.append(node("p","Official recorded crime comparison · 12 months ending March 2026","metric-label"));
   card.append(node("p",Number(comparison.crimesPer1000).toFixed(2),"metric"));
   card.append(node("p","Recorded crimes per 1,000 Rochdale residents; Greater Manchester average: "+Number(comparison.greaterManchesterPer1000).toFixed(2)+". This is the borough, not this postcode or ward.","metric-label"));
   card.append(link("Read Police.uk's ONS comparison ↗",comparison.url));
   blocks.push(card);
 }
 sources.append(link("GMP neighbourhood crime figures (2019–2026) ↗","https://www.gmp.police.uk/police-forces/greater-manchester-police/areas/greater-manchester-force-content/sd/stats-and-data/neighbourhood-crime/"),node("span"," · "),link("Police.uk data availability ↗","https://data.police.uk/changelog/"));
 blocks.push(more,sources);
 out("crime",blocks);
 recentCrimeReports();
}
function planning(d){
 const data=Array.isArray(d.constraints)?d.constraints:[];
 out("planning",[node("p",data.length+" data entries returned; some designation datasets may be incomplete.","news-count"),list(data.map(x=>({title:x.name||x.dataset||"Planning designation",meta:[x.dataset,x.reference].filter(Boolean).join(" · ")}))),node("p","No results does not prove that a property has no restrictions.","method")]);
}

function councillorCard(person){
 const card=node("article",undefined,"councillor-card");
 card.append(node("h3",person.name||"Councillor"),node("p",person.party||"Party not verified","councillor-party"));
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
  byId("location").hidden=true;byId("lookup").querySelector("button").disabled=false;
  const crimeLatest=byId("crime-latest");if(crimeLatest)crimeLatest.replaceChildren(node("p","Enter a valid postcode to see locally matched reporting. No borough-wide crime stories will be substituted.","method"));
  const fallback={district:"Rochdale",ward:"",latitude:53.615,longitude:-2.155};
  await Promise.allSettled([
    (async()=>{await newsArchive(fallback,requestId);active="all";news();})(),
    (async()=>{try{weather(await read("/weather.json"));}catch{unavailable("weather","https://www.metoffice.gov.uk/")}})(),
    (async()=>{try{traffic(await read("/api/traffic"),fallback);}catch{unavailable("traffic","https://tfgm.com/")}})(),
    (async()=>{try{events(await read("/api/events"));}catch{unavailable("events","/whats-on.html")}})()
  ]);
  services(fallback);
  ["flood","crime","planning"].forEach(id=>unavailable(id,errorSources[id],"This source requires a successful postcode lookup. Open the official service."));
}
const errorSources={councillors:"https://democracy.rochdale.gov.uk/mgMemberIndex.aspx?bcr=1",weather:"https://www.metoffice.gov.uk/",traffic:"https://tfgm.com/",events:"/whats-on.html",flood:"https://check-for-flooding.service.gov.uk/",crime:"https://data.police.uk/",planning:"https://www.planning.data.gov.uk/"};
async function start(e){
 e?.preventDefault();
 const input=byId("postcode").value.trim().toUpperCase();
 if(!/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/.test(input)){report("Enter a full UK postcode, for example OL16 1XU.","error");return;}
 const id=++requestId,button=byId("lookup").querySelector("button");button.disabled=true;
 button.textContent="Finding your area…";
 report("Looking up your postcode and preparing the latest crime reports, weather and news…","loading");
 status.scrollIntoView({behavior:"smooth",block:"center"});
 status.focus({preventScroll:true});
 ["stories","weather","traffic","events","flood","crime","planning","services"].forEach(k=>out(k,[node("p","Checking the source…","loading")]));
 byId("ward-councillors").hidden=true;
 byId("news-controls").replaceChildren();byId("roadworks").replaceChildren();lastEvents=null;
 archive=[];aliases=[];area={};archiveReadyForPostcode=false;
 const crimeLatest=byId("crime-latest");
 if(crimeLatest)crimeLatest.replaceChildren(node("p","Checking for published reports mentioning your neighbourhood…","loading"));
 for(const k of Object.keys(brief))delete brief[k];byId("daily-brief").hidden=true;
 try{
  const data=await safePostcodeLookup(input);
  if(id!==requestId)return;
  const loc=data.location;area=loc;
  byId("area-name").textContent=loc.ward||loc.district;
  byId("area-detail").textContent=(loc.nearbyWhitworth?"Whitworth and surrounding communities":"Rochdale borough")+" · Postcode location is approximate.";
  byId("area-postcode").textContent=loc.postcode;
  byId("location").hidden=false;
  report("✓ "+loc.ward+" found. Your local crime reports, weather and news are loading below.","success");
  byId("location").scrollIntoView({behavior:"smooth",block:"start"});
  services(loc);
  const param="&lat="+Number(loc.latitude).toFixed(3)+"&lon="+Number(loc.longitude).toFixed(3);
  const work=[
   ["councillors",()=>councillors(loc,id)],
   ["archive",()=>newsArchive(loc,id)],
   ["weather",()=>weatherForPostcode(param)],
   ["traffic",async()=>traffic(await read("/api/traffic"),loc)],
   ["events",async()=>events(await read("/api/events"))],
   ["flood",async()=>flood(await read("/api/borough-data?kind=flood"+param,19000))],
   ["crime",async()=>crime(await read("/api/borough-data?kind=crime"+param,16000))],
   ["planning",async()=>planning(await read("/api/borough-data?kind=planning"+param,16000))]
  ];
  await Promise.allSettled(work.map(async x=>{try{await x[1]();}catch(err){if(id===requestId){
      if(x[0]==="councillors"){
       byId("ward-councillors").hidden=false;
       byId("councillor-cards").replaceChildren(node("p","Councillor and voting records could not be loaded. Please consult Rochdale Council's official directory.","method"),
          link("Official councillor directory ↗",errorSources.councillors));
      }else unavailable(x[0]==="archive"?"stories":x[0],errorSources[x[0]]||"/archive.html");
     };}}));
  if(id===requestId)report("✓ Results ready for "+loc.ward+": crime and courts, weather, all news, travel and other local services.","success");
 }catch(err){if(id===requestId)await showBoroughIfLookupFails();}
 finally{if(id===requestId){button.disabled=false;button.textContent="Explore my area →";}}
}
byId("lookup").addEventListener("submit",start);
})();