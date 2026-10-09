/* Equal-weight banner rotation across existing and approved monthly advertisers.
 * Reuses existing tracking for established placements and the new private
 * reporting API for self-service banners. Runs once per loaded page.
 */
(async()=>{
'use strict';
const slots=['home-leaderboard','home-billboard'];
const londonDay=()=>{const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const v=Object.fromEntries(p.map(x=>[x.type,x.value]));return v.year+'-'+v.month+'-'+v.day;};
try {
 const [legacyRes,newRes]=await Promise.all([fetch('/adverts.json',{cache:'no-store'}),fetch('/api/banner-live',{cache:'no-store'})]);
 const legacy=legacyRes.ok?await legacyRes.json():{};
 const live=newRes.ok?await newRes.json():{items:[]};
 const active=(legacy.placements||[]).filter(x=>x.start<=londonDay()&&x.end>=londonDay());
 const modern=Array.isArray(live.items)?live.items:[];
 slots.forEach((slot,index)=>{
   const box=document.querySelector('[data-ad-slot="'+slot+'"]');if(!box)return;
   const pool=active.filter(x=>x.slot===slot&&x.image&&x.url).map(x=>({...x,origin:'legacy'}))
      .concat(modern.map(x=>({...x,origin:'selfservice'})));
   if(!pool.length)return;
   const choice=pool[Math.floor(Math.random()*pool.length)];
   const a=document.createElement('a');a.target='_blank';a.rel='sponsored noopener noreferrer';
   a.style.cssText='display:flex;align-items:center;justify-content:center;text-decoration:none;position:relative;width:100%;min-height:80px;box-sizing:border-box;overflow:hidden';
   if(choice.origin==='selfservice'){
     a.href=choice.click;a.style.backgroundColor=choice.colour||'#103349';a.style.color='#fff';
     a.style.padding=index?'22px 24px':'12px 20px';a.style.gap='15px';
     const logo=document.createElement('img');logo.src=choice.logo;logo.alt='';logo.loading='lazy';logo.style.cssText='max-width:30%;width:auto;max-height:'+(index?'150px':'80px')+';object-fit:contain';
     const words=document.createElement('span');words.textContent=index?choice.bottom:choice.top;
     words.style.cssText='font:700 clamp(15px,2.5vw,26px)/1.2 system-ui;text-align:center;overflow-wrap:anywhere';
     a.append(logo,words);
     const px=new Image();px.src='/api/banner-live?impression=1&id='+encodeURIComponent(choice.id)+'&t='+Date.now();
   }else {
     const base=String(legacy.config?.tracker_base||'').replace(/\/$/,'');
     a.href=base?base+'/go/'+encodeURIComponent(choice.id):choice.url;
     const img=document.createElement('img');img.src=choice.image;img.alt=choice.alt||choice.advertiser||'Advertisement';img.loading='lazy';img.style.cssText='display:block;max-width:100%;width:100%;height:auto;max-height:'+(index?280:120)+'px;object-fit:contain';a.append(img);
     if(base){const factor=Math.max(1,Number(legacy.config?.impression_sample)||1);if(Math.random()<1/factor){const px=new Image();px.src=base+'/px/'+encodeURIComponent(choice.id)+'.gif?s='+encodeURIComponent(slot)+'&t='+Date.now();}}
   }
   const label=document.createElement('span');label.textContent='Advertisement';label.style.cssText='position:absolute;top:0;left:0;background:#111;color:white;font:700 9px/1 system-ui;padding:4px 6px';a.append(label);
   box.replaceChildren(a);box.classList.add('ad-live');box.hidden=false;box.style.height='auto';box.setAttribute('aria-label','Advertisement: '+(choice.name||choice.advertiser||'Sponsored banner'));
 });
} catch(error) {console.warn('Banner rotation unavailable',error)}
})();
