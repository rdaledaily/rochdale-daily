// Advertising package enquiries are leads, never bookings, payments or approvals.
// Per-lead keys avoid races from rewriting a shared array. Stored for 180 days.
const PRICES=Object.freeze({corporate:1200,section:350,banner:175,directory:75});
const STATUSES=new Set(['new','contacted','quoted','agreed','closed']);
const resp=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
const safe=(x,max)=>String(x||'').trim().slice(0,max);
const mail=x=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x)&&x.length<=160;
const field=(x,max)=>typeof x==='string'&&x.length<=max;
const key=id=>'ads:lead:'+id;
const admin=(r,env)=>Boolean(env.EVENTS_ADMIN_TOKEN&&r.headers.get('x-admin-token')===env.EVENTS_ADMIN_TOKEN);
const retention=180*86400;
function normalise(d){
  if(!d||typeof d!=='object'||Array.isArray(d))return null;
  const plan=safe(d.package,20),business=safe(d.business,110),name=safe(d.name,100),
    email=safe(d.email,160),area=safe(d.area,110),goal=safe(d.goal,1300),website=safe(d.website,300);
  if(!Object.hasOwn(PRICES,plan)||business.length<2||!name||!mail(email)||!goal||!field(d.business,110)||!field(d.name,100)||!field(d.email,160)||!field(d.area||'',110)||!field(d.goal,1300)||!field(d.website||'',300))return null;
  if(website){try{const u=new URL(website);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)return null}catch{return null}}
  if(d.privacyAccepted!==true)return null;
  return {package:plan,quotedMonthlyPriceGBP:PRICES[plan],business,name,email,area,goal,website};
}
export async function onRequestPost({request,env}){
  const kv=env.EVENTS_KV;
  if(!kv)return resp({error:'Our online enquiry form is temporarily unavailable. Please email advertising@rochdaledaily.co.uk.'},503);
  const u=new URL(request.url);
  if(request.headers.get('origin')!==u.origin)return resp({error:'Invalid request origin'},403);
  if(Number(request.headers.get('content-length')||0)>5500)return resp({error:'Request too large'},413);
  let d;try{d=await request.json()}catch{return resp({error:'Invalid form submission'},400)}
  if(!d||typeof d!=='object'||Array.isArray(d))return resp({error:'Invalid form submission'},400);
  if(admin(request,env)&&d.action==='status'){
    const id=safe(d.id,90),status=safe(d.status,30);
    if(!/^lead-[0-9a-f-]{36}$/.test(id)||!STATUSES.has(status))return resp({error:'Invalid update'},400);
    const saved=await kv.get(key(id),{type:'json'});
    if(!saved)return resp({error:'Enquiry not found or expired'},404);
    // A status change is administrative metadata, not evidence of payment.
    saved.status=status;saved.updatedAt=new Date().toISOString();
    await kv.put(key(id),JSON.stringify(saved),{expirationTtl:retention});
    return resp({ok:true,id,status});
  }
  if(d.action)return resp({error:'Invalid action'},400);
  // Honeypot is deliberately not echoed. Bots do not enter the pipeline.
  if(safe(d.company_fax,150))return resp({ok:true,message:'Enquiry received.'});
  const data=normalise(d);if(!data)return resp({error:'Please complete your details, campaign aim and privacy confirmation.'},400);
  const id='lead-'+crypto.randomUUID();
  const lead={id,...data,status:'new',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()};
  try{await kv.put(key(id),JSON.stringify(lead),{expirationTtl:retention});}
  catch{return resp({error:'Could not save the enquiry. Please email advertising@rochdaledaily.co.uk.'},503)}
  return resp({ok:true,reference:id,message:'Your enquiry is recorded. This is not a confirmed booking, and no payment has been taken.'},201);
}
export async function onRequestGet({request,env}){
  if(!admin(request,env))return resp({error:'Unauthorised'},401);
  const kv=env.EVENTS_KV;if(!kv)return resp({error:'Unavailable'},503);
  let cursor,records=[];
  do{
    const page=await kv.list({prefix:'ads:lead:',limit:200,...(cursor?{cursor}:{})});
    const values=await Promise.all(page.keys.map(x=>kv.get(x.name,{type:'json'})));
    records.push(...values.filter(x=>x&&x.id));
    cursor=page.list_complete?null:page.cursor;
  }while(cursor&&records.length<500);
  records.sort((a,b)=>String(b.createdAt).localeCompare(String(a.createdAt)));
  return resp({leads:records.slice(0,300)});
}
