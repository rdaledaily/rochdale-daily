// Public OneSignal web application identity only. NEVER return REST API keys.
// Readers can browse Rochdale Daily without contacting OneSignal.
const response=(value)=>new Response(JSON.stringify(value),{headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
export async function onRequestGet({env}){
  const appId=String(env.ONESIGNAL_APP_ID||"").trim();
  const configured=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(appId);
  return response({ok:true,configured,appId:configured?appId:null,workerPath:"/OneSignalSDKWorker.js",scope:"/"});
}
