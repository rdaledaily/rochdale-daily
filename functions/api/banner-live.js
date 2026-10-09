// Approved banners, private logos, click-through reporting.
// KV counters are approximate under concurrent load; never describe as audited unique clicks.
const respond=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
const month=()=>new Date().toLocaleDateString('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit'}).slice(0,7);
async function rows(kv){const v=await kv.get('banners:claims',{type:'json'});return Array.isArray(v)?v:[]}
async function count(kv,id,type){const key='banner:stats:'+id+':'+type;const old=Number(await kv.get(key)||0);await kv.put(key,String(old+1));}
export async function onRequestGet({request,env}) {
 const kv=env.EVENTS_KV;if(!kv)return respond({items:[]},503);
 const u=new URL(request.url),claims=await rows(kv),id=u.searchParams.get('id')||'';
 if(u.searchParams.has('logo')) {
  const row=claims.find(x=>x.id===id&&x.status==='approved');if(!row)return new Response('Not found',{status:404});
  const data=await kv.get('banners:logo:'+id);if(!data)return new Response('Not found',{status:404});
  const match=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(data);if(!match)return new Response('Not found',{status:404});
  const bin=atob(match[2]);return new Response(Uint8Array.from(bin,x=>x.charCodeAt(0)),{headers:{'Content-Type':'image/'+match[1],'Cache-Control':'public, max-age=300','X-Content-Type-Options':'nosniff'}});
 }
 if(u.searchParams.has('click')){
  const row=claims.find(x=>x.id===id&&x.status==='approved'&&x.month===month());if(!row)return new Response('Not found',{status:404});
  await count(kv,id,'clicks');return Response.redirect(row.website,302);
 }
 if(u.searchParams.has('impression')){
  const row=claims.find(x=>x.id===id&&x.status==='approved'&&x.month===month());if(!row)return new Response(null,{status:204});
  await count(kv,id,'impressions');return new Response(null,{status:204,headers:{'Cache-Control':'no-store'}});
 }
 if(u.searchParams.has('report')){
  const key=u.searchParams.get('key')||'';const row=claims.find(x=>x.id===id);
  if(!row||!key)return respond({error:'Unauthorised'},403);
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(key));
  const hash=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(row.tokenHash!==hash)return respond({error:'Unauthorised'},403);
  const impressions=Number(await kv.get('banner:stats:'+id+':impressions')||0),clicks=Number(await kv.get('banner:stats:'+id+':clicks')||0);
  return respond({impressions,clicks,ctr:impressions?+(100*clicks/impressions).toFixed(2):0,status:row.status});
 }
 return respond({items:claims.filter(x=>x.status==='approved'&&x.month===month()).slice(0,10).map(x=>({
  id:x.id,name:x.name,top:x.top,bottom:x.bottom,colour:x.colour,logo:'/api/banner-live?logo=1&id='+encodeURIComponent(x.id),
  click:'/api/banner-live?click=1&id='+encodeURIComponent(x.id)
 }))});
}
