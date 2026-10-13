/* Public feature detection exposes only non-secret application IDs. */
export async function onRequestGet({env}){
 const id=String(env.ONESIGNAL_APP_ID||'').trim();
 const configured=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id);
 return new Response(JSON.stringify({ok:true,webPush:{configured,appId:configured?id:null},
   newsletter:{providerConfigured:Boolean(env.BREVO_API_KEY&&env.BREVO_LIST_ID)},
   advertisingBilling:{providerConfigured:Boolean(env.STRIPE_SECRET_KEY&&env.STRIPE_WEBHOOK_SECRET)},
   note:'Configuration presence only; this endpoint does not verify a provider connection, bill customers or send notifications.'}),
 {headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
}