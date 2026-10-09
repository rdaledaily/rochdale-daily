/* Paid reader story intake: NEVER autopublishes. Human approval and payment verification required. */
const reply=(v,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
const tidy=(v,n)=>String(v||"").trim().slice(0,n);
function prohibited(s){return /\b(murder|homicide|killed|killer|rape|raped|sexual assault|sexually assaulted|molest|grooming|sexuality|sexual orientation|gay|lesbian|bisexual|transgender|transsexual|queer|crime|criminal|arrested|charged|convicted|sentenced|theft|burglary|robbery|fraud|assault|stabbing|drugs|prosecution|court case|police investigation|fuck|fucking|shit|bitch|cunt|bastard|wanker|bollocks|motherfucker)\b/i.test(s)}
const validEmail=x=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x);
function isAdmin(req,env){return Boolean(env.EVENTS_ADMIN_TOKEN&&req.headers.get('x-admin-token')===env.EVENTS_ADMIN_TOKEN)}
async function read(kv){const a=await kv.get('stories:paid:submissions',{type:'json'});return Array.isArray(a)?a:[]}
function validImage(v){if(!v)return false;const m=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(v);if(!m||v.length>350000)return false;try{const x=atob(m[2]);return x.length<=250000&&(m[1]==='png'?x.startsWith('\x89PNG\r\n\x1a\n'):m[1]==='jpeg'?x.startsWith('\xff\xd8\xff'):x.startsWith('RIFF')&&x.slice(8,12)==='WEBP')}catch{return false}}
export async function onRequestPost({request,env}){
 const kv=env.EVENTS_KV;if(!kv)return reply({error:'Submissions are temporarily unavailable'},503);
 if(Number(request.headers.get('content-length')||0)>390000)return reply({error:'Upload too large'},413);
 let x;try{x=await request.json()}catch{return reply({error:'Invalid request'},400)}
 const action=tidy(x.action||'submit',20),records=await read(kv);
 if(action==='submit'){
  const title=tidy(x.title,130),body=tidy(x.body,9000),byline=tidy(x.byline,100),email=tidy(x.email,150),area=tidy(x.area,90),source=tidy(x.source,500),choice=tidy(x.imageChoice,10);
  if(title.length<15||body.length<250||!byline||!validEmail(email)||!area||!['upload','gallery'].includes(choice)||(!source&&body.length<500))return reply({error:'Complete all fields. Your story must be at least 250 characters and have a meaningful headline.'},400);
  if(prohibited([title,body,source,byline].join(' ')))return reply({error:'This topic or wording is not eligible for paid reader submissions.'},422);
  if(choice==='upload'&&!validImage(x.image))return reply({error:'Upload a PNG, JPG or WebP image smaller than 250 KB.'},400);
  if(records.filter(r=>r.status==='pending'||r.status==='awaiting_payment').length>=100)return reply({error:'Submission queue is full'},503);
  const id='reader-'+crypto.randomUUID(),now=new Date().toISOString();
  if(choice==='upload')await kv.put('stories:paid:image:'+id,x.image);
  records.push({id,title,body,byline,email,area,source,imageChoice:choice,status:'awaiting_payment',submittedAt:now,paymentConfirmed:false,editorialApproved:false,label:'Paid reader submission'});
  await kv.put('stories:paid:submissions',JSON.stringify(records));
  return reply({reference:id,paymentUrl:'https://pay.sumup.com/b2c/QD70LX24',message:'Submission saved for moderation. Pay £5 with SumUp and quote this reference. Payment never guarantees publication.'},201);
 }
 if(!isAdmin(request,env))return reply({error:'Unauthorised'},401);
 const row=records.find(r=>r.id===x.id);if(!row)return reply({error:'Not found'},404);
 if(action==='mark_paid'){row.paymentConfirmed=true;row.status='pending';}
 else if(action==='reject'){row.status='rejected';row.rejectReason=tidy(x.reason,400);}
 else if(action==='approve'){
  if(!row.paymentConfirmed)return reply({error:'Verify the £5 payment first'},409);
  if(prohibited([row.title,row.body,row.byline,row.source].join(' ')))return reply({error:'Submission violates editorial exclusions'},422);
  row.status='approved_for_manual_publication';row.editorialApproved=true;
 }else return reply({error:'Unknown action'},400);
 row.reviewedAt=new Date().toISOString();
 await kv.put('stories:paid:submissions',JSON.stringify(records));
 // Explicitly not written to public articles.json or any automatically published feed.
 return reply({ok:true,id:row.id,status:row.status});
}
export async function onRequestGet({request,env}){
 if(!isAdmin(request,env))return reply({error:'Unauthorised'},401);
 const kv=env.EVENTS_KV;if(!kv)return reply({error:'Not configured'},503);
 const url=new URL(request.url),records=await read(kv),id=url.searchParams.get('image');
 if(id){const row=records.find(r=>r.id===id);if(!row||row.imageChoice!=='upload')return new Response('Not found',{status:404});
 const raw=await kv.get('stories:paid:image:'+id);const m=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(raw||'');if(!m)return new Response('Not found',{status:404});
 return new Response(Uint8Array.from(atob(m[2]),x=>x.charCodeAt(0)),{headers:{'Content-Type':'image/'+m[1],'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }
 return reply({stories:records.slice(-100).reverse()});
}
