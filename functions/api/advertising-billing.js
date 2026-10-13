/* Admin-authorised Stripe subscription checkout for approved proposals.
 * Requires STRIPE_SECRET_KEY and STRIPE_PRICE_{CORPORATE,SECTION,BANNER,DIRECTORY}.
 * Creating a session does not take money or activate advertising. The
 * customer must explicitly pay in Stripe's hosted checkout.
 */
const PRICES={corporate:'STRIPE_PRICE_CORPORATE',section:'STRIPE_PRICE_SECTION',
  banner:'STRIPE_PRICE_BANNER',directory:'STRIPE_PRICE_DIRECTORY'};
const JSON_HEADERS={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
const answer=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:JSON_HEADERS});
const authorised=(request,env)=>Boolean(env.EVENTS_ADMIN_TOKEN&&request.headers.get('x-admin-token')===env.EVENTS_ADMIN_TOKEN);
const leadKey=id=>'ads:lead:'+id;
const safeLead=id=>/^lead-[0-9a-f-]{36}$/i.test(String(id||''));
function cfg(env,plan){
 const price=env[PRICES[plan]];
 if(!String(env.STRIPE_SECRET_KEY||'').startsWith('sk_')||!/^price_[a-zA-Z0-9]+$/.test(String(price||'')))return null;
 return {key:env.STRIPE_SECRET_KEY,price};
}
async function stripe(path,secret,form){
 const res=await fetch('https://api.stripe.com/v1/'+path,{
   method:form?'POST':'GET',
   headers:{Authorization:'Bearer '+secret,...(form?{'Content-Type':'application/x-www-form-urlencoded'}:{})},
   ...(form?{body:form.toString()}:{})
 });
 const data=await res.json().catch(()=>({}));
 if(!res.ok)throw Error(data.error?.message||'Stripe request failed');
 return data;
}
export async function onRequestGet({request,env}){
 if(!authorised(request,env))return answer({ok:false,error:'Unauthorised'},401);
 return answer({ok:true,configured:Boolean(env.STRIPE_SECRET_KEY&&Object.values(PRICES).every(k=>/^price_[a-zA-Z0-9]+$/.test(String(env[k]||'')))),
   note:'Stripe remains inactive until all secure Cloudflare variables and the signed webhook are configured. Subscription revenue is only confirmed by Stripe, not by enquiry status.'});
}
export async function onRequestPost({request,env}){
 if(!authorised(request,env))return answer({ok:false,error:'Unauthorised'},401);
 if(!env.EVENTS_KV)return answer({ok:false,error:'Lead storage unavailable'},503);
 if(request.headers.get('origin')&&request.headers.get('origin')!==new URL(request.url).origin)return answer({ok:false,error:'Invalid origin'},403);
 let body;try{body=await request.json();}catch{return answer({ok:false,error:'Invalid request'},400)}
 const leadId=String(body?.leadId||'');
 if(!safeLead(leadId))return answer({ok:false,error:'Invalid enquiry reference'},400);
 const lead=await env.EVENTS_KV.get(leadKey(leadId),{type:'json'});
 if(!lead)return answer({ok:false,error:'Enquiry no longer available'},404);
 if(lead.status!=='agreed')return answer({ok:false,error:'Agree the exact placement and written terms with the advertiser before creating a payment link.'},409);
 if(!Object.hasOwn(PRICES,lead.package))return answer({ok:false,error:'Unknown package'},400);
 const credentials=cfg(env,lead.package);
 if(!credentials)return answer({ok:false,error:'Stripe is not configured for this package. Set its approved Stripe recurring Price ID and secret in Cloudflare.'},503);
 if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(lead.email))return answer({ok:false,error:'Invalid advertiser email'},400);
 const prior=await env.EVENTS_KV.get('ads:subscription:'+leadId,{type:'json'});
 if(prior?.status==='active')return answer({ok:false,error:'An active subscription is already linked to this enquiry.'},409);
 const base='https://rochdaledaily.co.uk';
 const form=new URLSearchParams({
  mode:'subscription',customer_email:lead.email,client_reference_id:leadId,
  'line_items[0][price]':credentials.price,'line_items[0][quantity]':'1',
  'metadata[leadId]':leadId,'metadata[package]':lead.package,
  'subscription_data[metadata][leadId]':leadId,
  'subscription_data[metadata][package]':lead.package,
  success_url:base+'/advertise.html?checkout=returned&session_id={CHECKOUT_SESSION_ID}',
  cancel_url:base+'/advertise.html?checkout=cancelled'
 });
 try{
  const session=await stripe('checkout/sessions',credentials.key,form);
  if(!session.id||!/^https:\/\/checkout\.stripe\.com\//.test(session.url||''))throw Error('Stripe checkout response invalid');
  await env.EVENTS_KV.put('ads:checkout:'+leadId,JSON.stringify({id:session.id,createdAt:new Date().toISOString(),
    status:'checkout_link_created',package:lead.package}),{expirationTtl:86400});
  return answer({ok:true,checkoutUrl:session.url,sessionId:session.id,
    message:'Share this hosted checkout link with the advertiser. No payment has been taken, and no ad will activate automatically.'});
 }catch(e){return answer({ok:false,error:'Could not create Stripe checkout. '+String(e.message||'').slice(0,170)},502)}
}
