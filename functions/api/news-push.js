/* Private editorial OneSignal push publisher.
 * Never auto-publishes or sends every scraped article. Uses the LIVE deployed
 * archive as the authority for what was actually published.
 * Required env: EVENTS_ADMIN_TOKEN, EVENTS_KV, ONESIGNAL_APP_ID,
 * ONESIGNAL_REST_API_KEY.
 */
const TOPICS=new Set(['breaking','traffic','community','daily']);
const response=(v,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{
  'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',
  'X-Content-Type-Options':'nosniff'
}});
function isAdmin(request,env){
  const key=String(request.headers.get('x-admin-token')||''),expected=String(env.EVENTS_ADMIN_TOKEN||'');
  if(!expected||key.length!==expected.length)return false;
  let diff=0;for(let i=0;i<key.length;i++)diff|=key.charCodeAt(i)^expected.charCodeAt(i);
  return diff===0;
}
const str=(s,max)=>String(s||'').replace(/\s+/g,' ').trim().slice(0,max);
const slugOK=s=>/^[a-z0-9][a-z0-9-]{3,155}$/.test(s);
const appOK=s=>/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(s||''));
async function publishedStory(env,slug){
  if(!env.ASSETS?.fetch)throw Error('The deployed archive is not accessible.');
  const r=await env.ASSETS.fetch(new Request('https://rochdaledaily.co.uk/archive-index.json'));
  if(!r.ok)throw Error('Could not inspect the published archive.');
  const items=await r.json();
  if(!Array.isArray(items))throw Error('Published archive has an unexpected format.');
  const item=items.find(row=>row?.slug===slug);
  if(!item)throw Error('This slug is not in the currently deployed archive.');
  if(item.url!=='/articles/'+slug+'.html')throw Error('Article URL did not match the published slug.');
  const page=await env.ASSETS.fetch(new Request('https://rochdaledaily.co.uk'+item.url));
  if(!page.ok)throw Error('Article page is not live yet.');
  const title=str(item.title,125),description=str(item.description,220);
  if(title.length<15||!/^https?:\/\//.test('https://rochdaledaily.co.uk'+item.url))throw Error('Article metadata invalid.');
  return {slug,title,description,category:str(item.category,40),url:'https://rochdaledaily.co.uk'+item.url,
    publishedAt:str(item.published_at,35)};
}
function topicValid(topic,category){
  const cat=String(category||'').toLowerCase();
  if(topic==='traffic')return /^(traffic|transport)$/.test(cat);
  if(topic==='community')return /^(community|events|education|health|environment|sport|business)$/.test(cat);
  return true;
}
function ready(env){
  return appOK(env.ONESIGNAL_APP_ID)&&String(env.ONESIGNAL_REST_API_KEY||'').length>22&&Boolean(env.EVENTS_KV);
}
function statuses(kv,slug,topic){
  return {sent:'push:sent:'+slug+':'+topic,last:'push:global:last-send'};
}
async function preview({request,env},body){
  if(!slugOK(body.slug)||!TOPICS.has(body.topic))return response({ok:false,error:'Choose a published article and a valid topic.'},400);
  let article;
  try{article=await publishedStory(env,body.slug)}
  catch(e){return response({ok:false,error:str(e.message,160)},409)}
  if(!topicValid(body.topic,article.category))
    return response({ok:false,error:'This topic does not match the published article category.'},400);
  const kv=env.EVENTS_KV;
  const keys=statuses(kv,body.slug,body.topic);
  const sent=kv?await kv.get(keys.sent,{type:'json'}):null;
  const last=kv?Number(await kv.get(keys.last)||0):0;
  const wait=Math.max(0,15*60*1000-(Date.now()-last));
  return response({ok:true,article,topic:body.topic,configured:ready(env),alreadySent:!!sent,
    nextAllowedInSeconds:Math.ceil(wait/1000),
    audience:'Only opted-in subscribers with the selected '+body.topic+' topic tag. No postcode filtering.',
    note:'Review wording and verify publication before sending. Preview does not send an alert.'});
}
export async function onRequestGet({request,env}){
 if(!isAdmin(request,env))return response({ok:false,error:'Unauthorised'},401);
 return response({ok:true,configured:ready(env),topics:[...TOPICS],
   note:'The push sender requires a configured OneSignal app, REST API key, KV, and an editor-selected article.'});
}
export async function onRequestPost(context){
 const {request,env}=context;
 if(!isAdmin(request,env))return response({ok:false,error:'Unauthorised'},401);
 if(request.headers.get('origin')&&request.headers.get('origin')!==new URL(request.url).origin)
   return response({ok:false,error:'Invalid origin'},403);
 if(Number(request.headers.get('content-length')||0)>4500)return response({ok:false,error:'Too much data'},413);
 let body;try{body=await request.json()}catch{return response({ok:false,error:'Invalid JSON'},400)}
 if(!body||typeof body!=='object'||Array.isArray(body))return response({ok:false,error:'Invalid request'},400);
 body.slug=str(body.slug,170);body.topic=str(body.topic,25);
 if(body.action==='preview')return preview(context,body);
 if(body.action!=='send')return response({ok:false,error:'Unknown action'},400);
 if(body.confirm!==true)return response({ok:false,error:'Explicit editor confirmation required'},400);
 if(!ready(env))return response({ok:false,error:'OneSignal is not configured. Set ONESIGNAL_APP_ID, ONESIGNAL_REST_API_KEY and EVENTS_KV in Cloudflare.'},503);
 const responsePreview=await preview(context,body);
 if(!responsePreview.ok)return responsePreview;
 const data=await responsePreview.json();
 if(!data.ok)return response(data,409);
 if(data.alreadySent)return response({ok:false,error:'This article was already pushed to that topic. Duplicate prevented.'},409);
 if(data.nextAllowedInSeconds>0)return response({ok:false,error:'Rate limit active. Wait '+data.nextAllowedInSeconds+' seconds.'},429);
 const story=data.article;
 const summary=story.description.replace(/https?:\/\/\S+/g,'').slice(0,145);
 const message={
  app_id:env.ONESIGNAL_APP_ID,target_channel:'push',
  name:'Rochdale Daily | '+body.topic+' | '+story.slug,
  headings:{en:'Rochdale Daily: '+story.title.slice(0,85)},
  contents:{en:summary||'A new report is available to read on Rochdale Daily.'},
  url:story.url,ttl:body.topic==='breaking'?7200:21600,
  filters:[{field:'tag',key:'rd_topic_'+body.topic,relation:'=',value:'1'}]
 };
 const abort=new AbortController(),clock=setTimeout(()=>abort.abort(),12000);
 try{
  const result=await fetch('https://api.onesignal.com/notifications',{
    method:'POST',headers:{Authorization:'Key '+env.ONESIGNAL_REST_API_KEY,'Content-Type':'application/json; charset=utf-8'},
    body:JSON.stringify(message),signal:abort.signal
  });
  const replyJSON=await result.json().catch(()=>({}));
  if(!result.ok||!replyJSON.id)throw Error('OneSignal rejected the notification. '+str(replyJSON.errors?.[0]||replyJSON.error||result.status,120));
  const now=Date.now(),kv=env.EVENTS_KV,keys=statuses(kv,body.slug,body.topic);
  const log={id:replyJSON.id,slug:story.slug,topic:body.topic,createdAt:new Date(now).toISOString(),
    article:story.url,recipients:Number.isFinite(replyJSON.recipients)?replyJSON.recipients:null};
  await Promise.all([
   kv.put(keys.sent,JSON.stringify(log),{expirationTtl:90*86400}),
   kv.put(keys.last,String(now),{expirationTtl:3600}),
   kv.put('push:log:'+now,JSON.stringify(log),{expirationTtl:90*86400})
  ]);
  return response({ok:true,notificationId:replyJSON.id,recipients:log.recipients,article:story.url,
    message:'OneSignal accepted the notification request. This does not guarantee delivery or readership.'});
 }catch(e){return response({ok:false,error:str(e.message,180)},502)}
 finally{clearTimeout(clock)}
}
