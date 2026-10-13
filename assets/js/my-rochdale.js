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
const report=(s,bad=false)=>{status.textContent=s;status.classList.toggle("error",bad);};
const when=s=>{const d=Date.parse(s||"");return Number.isFinite(d)?new Date(d).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}):"";};
const norm=s=>String(s||"").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g," ").replace(/\s+/g," ").trim();
const whole=(t,x)=>x.length>3&&(" "+norm(t)+" ").includes(" "+norm(x)+" ");
const read=async (url,timeout=12000)=>{
 const ctl=new AbortController(),clock=setTimeout(()=>ctl.abort(),timeout);
 try{const response=await fetch(url,{signal:ctl.signal,cache:"no-store",headers:{Accept:"application/json"}});if(!response.ok)throw Error("Source returned "+response.status);const j=await response.json();if(j?.ok===false)throw Error(j.error||"Source unavailable");return j;}
 finally{clearTimeout(clock)}
};
const unavailable=(id,source,msg)=>out(id,[node("p",msg||"This data source is not responding. Its official website has the latest information."),link("Open the official source ↗",source)]);
let archive=[],aliases=[],active="local",category="all",search="",page=0,requestId=0,area={};
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
  roadworks();
 }catch{unavailable("stories","/archive.html","Full news archive could not load. Open the archive to search directly.");}
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
 host.append(grid,node("p","Rochdale-area forecast, not a hyperlocal measurement.","method"));out("weather",[host]);
}
function traffic(d,loc){
 const data=Array.isArray(d.disruptions)?d.disruptions:[];
 const nearby=x=>Number.isFinite(x.lat)&&Number.isFinite(x.lon)?Math.sqrt(Math.pow((x.lat-loc.latitude)*111,2)+Math.pow((x.lon-loc.longitude)*66,2)):999;
 const sorted=data.slice().sort((a,b)=>nearby(a)-nearby(b));
 const rows=sorted.slice(0,20).map(x=>({title:String(x.summary||x.description||"Bus disruption").slice(0,180),meta:[nearby(x)<6?"Near this postcode":'Borough-wide notice',x.places?.slice(0,3).join(", "),x.lines?.length?"Services "+x.lines.slice(0,6).join(", "):"",x.end?"Listed until "+when(x.end):""].filter(Boolean).join(" · ")}));
 out("traffic",[node("p",data.length+" bus disruption notices in the borough feed.","news-count"),list(rows),node("p","This feed covers reported bus disruptions, not all road traffic or train cancellations.","method")]);
}
function events(d){
 const data=Array.isArray(d.events)?d.events:[];
 const scored=data.slice().sort((a,b)=>{
  const ma=aliases.some(x=>whole(a.event_location+" "+a.title,x)),mb=aliases.some(x=>whole(b.event_location+" "+b.title,x));
  return Number(mb)-Number(ma)||Date.parse(a.event_start_at||0)-Date.parse(b.event_start_at||0);
 });
 const rows=scored.slice(0,20).map(x=>({title:x.title||"Event",href:/^[a-z0-9-]+$/i.test(x.slug||"")?"/articles/"+x.slug+".html":undefined,meta:[when(x.event_start_at),x.event_location,x.event_cost].filter(Boolean).join(" · ")}));
 out("events",[node("p",data.length+" approved upcoming community events.","news-count"),list(rows)]);
}
function flood(d){
 const result=[],warnings=Array.isArray(d.warnings)?d.warnings:[],stations=Array.isArray(d.stations)?d.stations:[];
 if(!d.warningsAvailable)result.push(node("p","The warning feed could not be checked. Check the official service.","risk"));
 else if(!warnings.length)result.push(node("p","No warnings returned for this vicinity. Do not rely on this page for flood safety."));
 result.push(list(warnings.slice(0,12).map(x=>({title:x.area||"Warning",meta:[x.level,x.message].filter(Boolean).join(" · ")}))));
 if(stations.length)result.push(node("h4","Nearby river measuring stations"));
 result.push(list(stations.slice(0,9).map(x=>({title:x.name||x.station,href:x.url,meta:[x.river,x.reading?.value!=null?"Reading: "+x.reading.value+" (unit depends on station)":"No recent measurement",x.reading?.dateTime?when(x.reading.dateTime):""].filter(Boolean).join(" · ")}))));
 out("flood",result);
}
function crime(d){
 const rows=(d.byCategory||[]).map(x=>({title:String(x.category||"").replace(/-/g," "),meta:x.count+" reports"}));
 out("crime",[node("p",String(d.total||0),"metric"),node("p","Police-recorded reports for "+String(d.month||"latest published month")+", approximately one mile around the postcode.","metric-label"),list(rows)]);
}
function planning(d){
 const data=Array.isArray(d.constraints)?d.constraints:[];
 out("planning",[node("p",data.length+" data entries returned; some designation datasets may be incomplete.","news-count"),list(data.map(x=>({title:x.name||x.dataset||"Planning designation",meta:[x.dataset,x.reference].filter(Boolean).join(" · ")}))),node("p","No results does not prove that a property has no restrictions.","method")]);
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
 if(loc.nearbyWhitworth)rows.shift();
 out("services",[list(rows.map(x=>({title:x[0],href:x[1],meta:x[2]})))]);
}
const errorSources={weather:"https://www.metoffice.gov.uk/",traffic:"https://tfgm.com/",events:"/whats-on.html",flood:"https://check-for-flooding.service.gov.uk/",crime:"https://data.police.uk/",planning:"https://www.planning.data.gov.uk/"};
async function start(e){
 e?.preventDefault();
 const input=byId("postcode").value.trim().toUpperCase();
 if(!/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/.test(input)){report("Enter a full UK postcode, for example OL16 1XU.",true);return;}
 const id=++requestId,button=byId("lookup").querySelector("button");button.disabled=true;
 report("Finding your ward and connecting to local information…");
 ["stories","weather","traffic","events","flood","crime","planning","services"].forEach(k=>out(k,[node("p","Checking the source…","loading")]));
 byId("news-controls").replaceChildren();byId("roadworks").replaceChildren();
 try{
  const data=await read("/api/borough-data?kind=area&postcode="+encodeURIComponent(input),12000);
  if(id!==requestId)return;
  const loc=data.location;area=loc;
  byId("area-name").textContent=loc.ward||loc.district;
  byId("area-detail").textContent=(loc.nearbyWhitworth?"Whitworth and surrounding communities":"Rochdale borough")+" · Postcode location is approximate.";
  byId("area-postcode").textContent=loc.postcode;
  byId("location").hidden=false;
  report("Showing news and services for "+loc.ward+". Each data source has its own coverage and update schedule.");
  services(loc);
  const param="&postcode="+encodeURIComponent(input);
  const work=[
   ["archive",()=>newsArchive(loc,id)],
   ["weather",async()=>weather(await read("/weather.json"))],
   ["traffic",async()=>traffic(await read("/api/traffic"),loc)],
   ["events",async()=>events(await read("/api/events"))],
   ["flood",async()=>flood(await read("/api/borough-data?kind=flood"+param,19000))],
   ["crime",async()=>crime(await read("/api/borough-data?kind=crime"+param,16000))],
   ["planning",async()=>planning(await read("/api/borough-data?kind=planning"+param,16000))]
  ];
  await Promise.allSettled(work.map(async x=>{try{await x[1]();}catch(err){if(id===requestId)unavailable(x[0]==="archive"?"stories":x[0],errorSources[x[0]]||"/archive.html");}}));
 }catch(err){if(id===requestId)report("Postcode lookup was unsuccessful. "+String(err.message||"Check the postcode and try again."),true);}
 finally{if(id===requestId)button.disabled=false;}
}
byId("lookup").addEventListener("submit",start);
})();