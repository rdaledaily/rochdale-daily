// Banner submissions are pending until manual payment verification and approval.
// EVENTS_KV stores private logos and edit tokens; no client can self-publish.
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
const tidy=(v,n)=>String(v||"").trim().slice(0,n);
// Fixed launch price for a full future calendar month; payment is verified manually.
const BANNER_PRICE_GBP=175;
const validUrl=v=>{try{const u=new URL(v);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password}catch{return false}};
const emailOK=v=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
const monthOK=v=>/^20\d\d-(0[1-9]|1[0-2])$/.test(v);
function firstBookableMonth(){
 const dateParts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'numeric'}).formatToParts(new Date());
 const year=Number(dateParts.find(x=>x.type==='year').value),month=Number(dateParts.find(x=>x.type==='month').value);
 const next=new Date(Date.UTC(year,month,1));return next.toISOString().slice(0,7);
}
async function hash(v){const d=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(v));return [...new Uint8Array(d)].map(x=>x.toString(16).padStart(2,'0')).join('')}
function admin(req,env){return Boolean(env.EVENTS_ADMIN_TOKEN&&req.headers.get('x-admin-token')===env.EVENTS_ADMIN_TOKEN)}
async function records(kv){const x=await kv.get('banners:claims',{type:'json'});return Array.isArray(x)?x:[]}
const revisionOf=row=>Number(row.revision||1);
const logoKey=(id,revision)=>'banners:logo:'+id+':r'+revision;
const fenceKey=id=>'banners:current-revision:'+id;
const reviewKey=(id,revision)=>'banners:review:'+id+':r'+revision;
async function logoFor(kv,row){
 const rev=revisionOf(row);
 // Historical r1 artwork was stored under the unversioned key.
 return await kv.get(logoKey(row.id,rev))||(rev===1?await kv.get('banners:logo:'+row.id):null);
}
async function isCurrent(kv,row){
 return Number(await kv.get(fenceKey(row.id))||revisionOf(row))===revisionOf(row);
}
async function fingerprint(row,logo){
 return hash(JSON.stringify([row.id,revisionOf(row),row.name,row.website,row.top,row.bottom,row.colour,row.month,await hash(logo)]));
}
function checkLogo(v){if(typeof v!=='string'||v.length>280000)return false;const m=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(v);if(!m)return false;let bin;try{bin=atob(m[2])}catch{return false}if(bin.length>200000)return false;return m[1]==='png'?bin.startsWith('\x89PNG\r\n\x1a\n'):m[1]==='jpeg'?bin.startsWith('\xff\xd8\xff'):bin.startsWith('RIFF')&&bin.slice(8,12)==='WEBP'}
function validated(d,allowMissing=false){const name=tidy(d.name,100),email=tidy(d.email,150),website=tidy(d.website,1000),top=tidy(d.top,85),bottom=tidy(d.bottom,125),month=tidy(d.month,7),colour=tidy(d.colour||'#103349',7);
 if(!name||!emailOK(email)||!validUrl(website)||!top||!bottom||!monthOK(month)||!/^#[0-9a-fA-F]{6}$/.test(colour)||(!allowMissing&&!checkLogo(d.logo))||(d.logo&&!checkLogo(d.logo)))return null;
 if(String(d.top||'').length>85||String(d.bottom||'').length>125)return null;
 return {name,email,website,top,bottom,month,colour};
}
export async function onRequestPost({request,env}) {
 const kv=env.EVENTS_KV;if(!kv)return json({error:'Submission service unavailable'},503);
 if(Number(request.headers.get('content-length')||0)>300000)return json({error:'Upload is too large'},413);
 let d;try{d=await request.json()}catch{return json({error:'Invalid JSON'},400)}
 const action=tidy(d.action||'submit',20);const rows=await records(kv);
 if(action==='submit'){
  const fields=validated(d);if(!fields)return json({error:'Check all fields, logo (max 200 KB), and background colour'},400);
  if(fields.month<firstBookableMonth())return json({error:'Only full future calendar months can be booked at the founding rate. Contact advertising for current-month quotes.'},400);
  // Cap counts bookings being processed too, to avoid overselling.
  if(rows.filter(r=>r.month===fields.month&&['pending','approved'].includes(r.status)).length>=8)return json({error:'All eight new-advertiser spaces are reserved for this month (two existing sponsors also rotate). Choose another month.'},409);
  const id='ban-'+crypto.randomUUID(),token=crypto.randomUUID()+crypto.randomUUID();
  await kv.put(logoKey(id,1),d.logo);
  await kv.put(fenceKey(id),'1');
  rows.push({id,...fields,priceGBP:BANNER_PRICE_GBP,paymentStatus:'unpaid',revision:1,tokenHash:await hash(token),status:'pending',createdAt:new Date().toISOString()});
  await kv.put('banners:claims',JSON.stringify(rows));
  return json({reference:id,priceGBP:BANNER_PRICE_GBP,paymentStatus:'unpaid',editToken:token,editUrl:'/manage-banner.html?id='+encodeURIComponent(id)+'&key='+encodeURIComponent(token)},201);
 }
 if(action==='edit'){
  const id=tidy(d.id,100),token=tidy(d.token,150);const row=rows.find(r=>r.id===id);
  if(!row||!token||row.tokenHash!==await hash(token))return json({error:'Invalid edit reference'},403);
  const fields=validated({...row,...d,month:row.month},true);if(!fields)return json({error:'Invalid banner details'},400);
  if(row.status==='rejected')return json({error:'Please contact the newsdesk about this booking'},403);
  if(!await isCurrent(kv,row))return json({error:'Booking changed. Reload before editing.'},409);
  const nextRevision=revisionOf(row)+1,logo=d.logo||await logoFor(kv,row);
  if(!checkLogo(logo))return json({error:'Existing artwork is missing or invalid'},409);
  // New logo key is immutable; a text-only edit copies the existing bytes.
  await kv.put(logoKey(id,nextRevision),logo);
  // Review actions never move this revision fence, so stale approvals fail
  // closed in the public banner endpoint even if KV writes race.
  await kv.put(fenceKey(id),String(nextRevision));
  Object.assign(row,fields,{status:'pending',revision:nextRevision,artworkReviewedAt:null,artworkReviewedRevision:null,artworkReviewedFingerprint:null,updatedAt:new Date().toISOString()});
  await kv.put('banners:claims',JSON.stringify(rows));
  return json({ok:true,message:'Changes saved and sent for editorial review'});
 }
 if(action==='mark-paid'){
  if(!admin(request,env))return json({error:'Unauthorised'},401);
  const row=rows.find(r=>r.id===tidy(d.id,100));if(!row)return json({error:'Not found'},404);
  if(row.status==='rejected')return json({error:'Rejected booking cannot be paid'},409);
  const paymentReference=tidy(d.paymentReference,120);
  if(paymentReference.length<4)return json({error:'Enter the verified payment transaction reference'},400);
  // This action must be performed only after checking the exact received amount in the payment provider.
  if(!await isCurrent(kv,row))return json({error:'Booking changed. Reload before verifying payment.'},409);
  row.paymentStatus='paid';row.paymentReference=paymentReference;
  row.paymentVerifiedAt=new Date().toISOString();row.paymentVerifiedAmountGBP=BANNER_PRICE_GBP;
  await kv.put('banners:claims',JSON.stringify(rows));
  return json({ok:true,paymentStatus:'paid'});
 }
 if(action==='review-artwork'){
  if(!admin(request,env))return json({error:'Unauthorised'},401);
  const row=rows.find(r=>r.id===tidy(d.id,100));if(!row)return json({error:'Not found'},404);
  if(row.status!=='pending')return json({error:'Only pending artwork can be reviewed'},409);
  const revision=Number(row.revision||1);
  if(!Number.isInteger(d.revision)||d.revision!==revision)return json({error:'Artwork changed. Reload and review the current version.'},409);
  const logo=await logoFor(kv,row);
  if(!validated(row,true)||!checkLogo(logo))return json({error:'Artwork is missing or invalid'},409);
  if(!await isCurrent(kv,row))return json({error:'Artwork changed. Reload and review the current version.'},409);
  const artworkReviewedAt=new Date().toISOString();
  const digest=await fingerprint(row,logo);
  // Review writes only this revision-specific marker, never a stale claims
  // snapshot that could revert a newer advertiser edit.
  await kv.put(reviewKey(row.id,revision),JSON.stringify({fingerprint:digest,at:artworkReviewedAt}));
  return json({ok:true,artworkReviewedRevision:revision,artworkReviewedAt});
 }
 if(action==='approve'||action==='reject'){
  if(!admin(request,env))return json({error:'Unauthorised'},401);
  const row=rows.find(r=>r.id===d.id);if(!row)return json({error:'Not found'},404);
  if(!await isCurrent(kv,row))return json({error:'Booking changed. Reload and try again.'},409);
  if(Number(d.revision)!==revisionOf(row))return json({error:'Artwork revision changed. Reload before approval or rejection.'},409);
  if(action==='approve'&&row.status!=='pending')return json({error:'Only pending banners can be approved'},409);
  if(action==='approve'&&row.paymentStatus!=='paid')return json({error:'Verify payment in the provider before approval'},409);
  const currentLogo=action==='approve'?await logoFor(kv,row):null;
  const review=action==='approve'?await kv.get(reviewKey(row.id,revisionOf(row)),{type:'json'}):null;
  const digest=action==='approve'&&checkLogo(currentLogo)?await fingerprint(row,currentLogo):'';
  // A pre-migration approved booking may have an unversioned r1 logo. Newly
  // submitted banners must have a digest for their exact creative revision.
  const legacyReviewed=action==='approve'&&revisionOf(row)===1&&!await kv.get(logoKey(row.id,1))&&
    Boolean(row.artworkReviewedAt)&&Number(row.artworkReviewedRevision)===1;
  if(action==='approve'&&!(review?.fingerprint===digest&&digest||legacyReviewed))
   return json({error:'Preview and review the current artwork before approval'},409);
  if(action==='approve'){
   row.artworkReviewedAt=review?.at||row.artworkReviewedAt;
   row.artworkReviewedRevision=revisionOf(row);
   row.artworkReviewedFingerprint=review?.fingerprint||null;
  }
  if(action==='approve'&&rows.filter(r=>r.month===row.month&&r.status==='approved'&&r.id!==row.id).length>=8)return json({error:'Month already full'},409);
  if(!await isCurrent(kv,row))return json({error:'Booking changed during approval. Reload.'},409);
  row.status=action==='approve'?'approved':'rejected';row.reviewedAt=new Date().toISOString();
  await kv.put('banners:claims',JSON.stringify(rows));return json({ok:true,status:row.status});
 }
 return json({error:'Unknown action'},400);
}
export async function onRequestGet({request,env}) {
 const kv=env.EVENTS_KV;if(!kv)return json({error:'Unavailable'},503);
 const u=new URL(request.url),rows=await records(kv);
 // Pending logos must never be public. Editor fetches through an authenticated request,
 // then builds a temporary local object URL instead of putting credentials in an image URL.
 if(u.searchParams.has('preview-logo')){
  if(!admin(request,env))return json({error:'Unauthorised'},401);
  const row=rows.find(r=>r.id===u.searchParams.get('id'));if(!row)return json({error:'Not found'},404);
  const expected=Number(u.searchParams.get('revision'));
  if(expected!==revisionOf(row)||!await isCurrent(kv,row))return json({error:'Artwork changed. Reload and preview the current version.'},409);
  const data=await logoFor(kv,row);
  if(!checkLogo(data))return json({error:'Logo missing or invalid'},404);
  const match=/^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(data);
  const binary=atob(match[2]);
  return new Response(Uint8Array.from(binary,x=>x.charCodeAt(0)),{headers:{'Content-Type':'image/'+match[1],'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}});
 }
 if(admin(request,env)){
  const claims=await Promise.all(rows.map(async row=>{
   const {tokenHash,...r}=row;
   if(row.status==='pending'&&await isCurrent(kv,row)){
    const logo=await logoFor(kv,row);
    const review=checkLogo(logo)?await kv.get(reviewKey(row.id,revisionOf(row)),{type:'json'}):null;
    if(review?.fingerprint===await fingerprint(row,logo)){
     r.artworkReviewedAt=review.at;
     r.artworkReviewedRevision=revisionOf(row);
    }
   }
   return r;
  }));
  return json({claims});
 }
 const id=u.searchParams.get('id')||'',key=u.searchParams.get('key')||'',row=rows.find(r=>r.id===id);
 if(!row||!key||row.tokenHash!==await hash(key))return json({error:'Unauthorised'},403);
 const {tokenHash,...publicRow}=row;return json({...publicRow,hasLogo:true});
}
