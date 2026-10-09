/* Paid reader story intake: NEVER autopublishes. Human approval and payment verification required. */
const reply=(v,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
const tidy=(v,n)=>String(v||"").trim().slice(0,n);
function prohibited(s){return /\b(murder|homicide|killed|killer|rape|raped|sexual assault|sexually assaulted|molest|grooming|sexuality|sexual orientation|gay|lesbian|bisexual|transgender|transsexual|queer|crime|criminal|arrested|charged|convicted|sentenced|theft|burglary|robbery|fraud|assault|stabbing|drugs|prosecution|court case|police investigation|fuck|fucking|shit|bitch|cunt|bastard|wanker|bollocks|motherfucker)\b/i.test(s)}
const ALLOWED_CATEGORIES=new Set(['community','events','business','education','sport','health','environment','news']);
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
  const title=tidy(x.title,130),body=tidy(x.body,9000),byline=tidy(x.byline,100),email=tidy(x.email,150),area=tidy(x.area,90),category=tidy(x.category,40).toLowerCase(),source=tidy(x.source,500),choice=tidy(x.imageChoice,10);
  if(title.length<15||body.length<250||!byline||!validEmail(email)||!area||!ALLOWED_CATEGORIES.has(category)||!['upload','gallery'].includes(choice)||(!source&&body.length<500))return reply({error:'Complete all fields. Your story must be at least 250 characters and have a meaningful headline.'},400);
  if(prohibited([title,body,source,byline].join(' ')))return reply({error:'This topic or wording is not eligible for paid reader submissions.'},422);
  if(choice==='upload'&&!validImage(x.image))return reply({error:'Upload a PNG, JPG or WebP image smaller than 250 KB.'},400);
  if(records.filter(r=>r.status==='pending'||r.status==='awaiting_payment').length>=100)return reply({error:'Submission queue is full'},503);
  const id='reader-'+crypto.randomUUID(),now=new Date().toISOString();
  if(choice==='upload')await kv.put('stories:paid:image:'+id,x.image);
  records.push({id,title,body,byline,email,area,category,source,commentsEnabled:true,imageChoice:choice,status:'awaiting_payment',submittedAt:now,paymentConfirmed:false,editorialApproved:false,label:'Paid reader submission'});
  await kv.put('stories:paid:submissions',JSON.stringify(records));
  return reply({reference:id,paymentUrl:'https://pay.sumup.com/b2c/QD70LX24',message:'Submission saved for moderation. Pay £5 with SumUp and quote this reference. Payment never guarantees publication.'},201);
 }
 if(!isAdmin(request,env))return reply({error:'Unauthorised'},401);
 const row=records.find(r=>r.id===x.id);if(!row)return reply({error:'Not found'},404);
 if(action==='save'){
  if(row.status==='published')return reply({error:'Published stories cannot be edited here'},409);
  const next={title:tidy(x.title,130),body:tidy(x.body,9000),byline:tidy(x.byline,100),area:tidy(x.area,90),category:tidy(x.category,40).toLowerCase()};
  if(next.title.length<15||next.body.length<250||!next.byline||!next.area||!ALLOWED_CATEGORIES.has(next.category)||prohibited(Object.values(next).join(' ')))return reply({error:'Invalid or prohibited story content'},422);
  Object.assign(row,next);row.editorialApproved=false;if(row.paymentConfirmed)row.status='pending';row.editedAt=new Date().toISOString();
 }
 else if(action==='publish'){
  if(!row.paymentConfirmed||!row.editorialApproved||row.status!=='approved_for_manual_publication')return reply({error:'Verify payment and approve editorial copy before publishing'},409);
  if(!env.STORIES_GITHUB_TOKEN)return reply({error:'GitHub publishing is not configured (STORIES_GITHUB_TOKEN)'},503);
  if(!ALLOWED_CATEGORIES.has(row.category)||prohibited([row.title,row.body,row.byline,row.area].join(' ')))return reply({error:'Story failed final policy check'},422);
  if(row.imageChoice==='upload')return reply({error:'An uploaded image needs manual preparation and credit verification before publishing. Choose a gallery image in the publishing workflow.'},409);
  const slug='paid-reader-'+row.id.replace(/[^a-z0-9-]/g,'').slice(0,55);
  const now=new Date().toISOString();
  const story={
    id:row.id,slug,title:row.title,body:'Paid reader submission.\\n\\n'+row.body,
    byline:row.byline,area:row.area,category:row.category,
    source_name:'Paid reader submission',source_kind:'paid_reader_submission',
    image_url:'/assets/img/cards/rochdale_riverside.jpg',
    image_credit:'Rochdale Daily gallery',published_at:now,
    paid_submission:true,advertisement:true,comments_enabled:true,
    legal_disclaimer:'Paid reader submission. Submitted by a reader and published after editorial review. This is not independent Rochdale Daily reporting.',
  };
  const file='manual_articles.d/paid-readers/'+slug+'.json';
  const encoded=btoa(unescape(encodeURIComponent(JSON.stringify(story,null,2)+'\\n')));
  const result=await fetch('https://api.github.com/repos/rdaledaily/rochdale-daily/contents/'+file,{
    method:'PUT',headers:{Authorization:'Bearer '+env.STORIES_GITHUB_TOKEN,Accept:'application/vnd.github+json','Content-Type':'application/json','User-Agent':'RochdaleDailyStoryPublisher'},
    body:JSON.stringify({message:'Publish reviewed paid reader submission '+row.id,content:encoded,branch:'main'})
  });
  if(!result.ok){const reason=await result.text();return reply({error:'GitHub publishing failed: '+result.status,detail:reason.slice(0,180)},502);}
  row.status='published';row.publishedAt=now;row.slug=slug;row.publicationFile=file;
 }
 else if(action==='mark_paid'){row.paymentConfirmed=true;row.status='pending';}
 else if(action==='reject'){row.status='rejected';row.rejectReason=tidy(x.reason,400);}
 else if(action==='approve'){
  if(!row.paymentConfirmed)return reply({error:'Verify the £5 payment first'},409);
  if(!ALLOWED_CATEGORIES.has(row.category)||prohibited([row.title,row.body,row.byline,row.source].join(' ')))return reply({error:'Submission violates editorial exclusions'},422);
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
