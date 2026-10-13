/* Stripe webhooks: signature-verified payment truth, never ad activation.
 * Set STRIPE_WEBHOOK_SECRET in Cloudflare, configure Stripe webhook events:
 * checkout.session.completed, invoice.paid, invoice.payment_failed,
 * customer.subscription.deleted, customer.subscription.updated.
 */
const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'};
const response=(v,s=200)=>new Response(JSON.stringify(v),{status:s,headers});
const safe=(x,max=120)=>String(x||'').slice(0,max);
function signatures(h){
 const a=Object.create(null);
 for(const s of String(h||'').split(',')){
   const parts=s.trim().split('=');if(parts.length===2) (a[parts[0]]||=[]).push(parts[1]);
 }
 return a;
}
function sameHex(a,b){
 if(a.length!==b.length)return false;
 let diff=0;for(let i=0;i<a.length;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);
 return diff===0;
}
async function verify(raw,header,secret){
 const h=signatures(header),timestamp=Number(h.t?.[0]);
 if(!Number.isFinite(timestamp)||Math.abs(Date.now()/1000-timestamp)>300||!h.v1?.length)return false;
 const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const buf=await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(timestamp+'.'+raw));
 const hex=Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
 return h.v1.some(v=>sameHex(v,hex));
}
const EVENTS=new Set(['checkout.session.completed','invoice.paid','invoice.payment_failed',
  'customer.subscription.deleted','customer.subscription.updated']);
const validLead=x=>/^lead-[0-9a-f-]{36}$/i.test(x||'');
export async function onRequestPost({request,env}){
 if(!env.STRIPE_WEBHOOK_SECRET||!env.EVENTS_KV)return response({error:'Webhook unconfigured'},503);
 const raw=await request.text();
 if(raw.length>500000)return response({error:'Payload too large'},413);
 if(!await verify(raw,request.headers.get('stripe-signature'),env.STRIPE_WEBHOOK_SECRET))
   return response({error:'Signature verification failed'},400);
 let event;try{event=JSON.parse(raw)}catch{return response({error:'Invalid event'},400)}
 if(!/^evt_[A-Za-z0-9]+$/.test(event.id||''))return response({error:'Invalid event id'},400);
 if(!EVENTS.has(event.type))return response({received:true,ignored:true});
 const kv=env.EVENTS_KV;
 if(await kv.get('stripe:seen:'+event.id))return response({received:true,duplicate:true});
 const obj=event.data?.object||{},type=event.type;
 const leadId=safe(obj.client_reference_id||obj.metadata?.leadId||obj.parent?.subscription_details?.metadata?.leadId,90);
 const subId=safe(obj.subscription||obj.parent?.subscription_details?.subscription||obj.id,100);
 const checkedSub=/^sub_[A-Za-z0-9]+$/.test(subId)?subId:'';
 const state={
   type,receivedAt:new Date().toISOString(),
   eventId:event.id,subscription:checkedSub,
   invoice:safe(type.startsWith('invoice.')?obj.id:'',110),
   amountPaidPence:Number.isInteger(obj.amount_paid)?obj.amount_paid:null,
   currency:safe(obj.currency||'',12),
   paymentStatus:safe(obj.payment_status||'',25),
   status:safe(obj.status||'',30)
 };
 if(checkedSub)await kv.put('stripe:subscription:'+checkedSub,JSON.stringify(state));
 if(validLead(leadId)){
   // A successful checkout is NOT the same as a paid invoice. A paid invoice
   // is recorded as financial evidence, never as artwork approval.
   await kv.put('ads:billing:'+leadId,JSON.stringify({...state,leadId}));
   if(checkedSub){
     const previous=(await kv.get('ads:subscription:'+leadId,{type:'json'}))||{};
     const status=type==='invoice.paid'&&state.currency==='gbp'?'active':
       type==='invoice.payment_failed'?'past_due':
       type==='customer.subscription.deleted'?'cancelled':
       previous.status||'pending';
     await kv.put('ads:subscription:'+leadId,JSON.stringify({
       leadId,subscription:checkedSub,status,updatedAt:state.receivedAt,
       lastPaidInvoice:type==='invoice.paid'?state.invoice:(previous.lastPaidInvoice||''),
       lastAmountPaidPence:type==='invoice.paid'?state.amountPaidPence:(previous.lastAmountPaidPence||null)
     }));
   }
 }
 await kv.put('stripe:seen:'+event.id,'1',{expirationTtl:2592000});
 return response({received:true});
}
