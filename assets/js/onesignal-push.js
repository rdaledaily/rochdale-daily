/* Optional OneSignal Web Push, SDK v16. Explicit opt-in only.
 * The external OneSignal SDK is not loaded until the reader clicks Subscribe.
 * No postcode, email or sensitive page names are sent as user tags.
 */
(function () {
"use strict";
const form=document.getElementById("rd-push-form");
if(!form)return;
const status=document.getElementById("rd-push-status");
const start=document.getElementById("rd-push-subscribe");
const stop=document.getElementById("rd-push-unsubscribe");
const controls=Array.from(form.querySelectorAll('input[name="topic"]'));
const categories=new Set(["breaking","traffic","community","daily"]);
let sdkPromise=null,os=null,appId=null;
function tell(s,type){
 status.textContent=s;
 status.dataset.state=type||"ready";
 status.setAttribute("role","status");
}
function selected(){
 return controls.filter(x=>x.checked&&categories.has(x.value)).map(x=>x.value);
}
function setButtons(){
 if(!os){stop.hidden=true;return;}
 const subscribed=!!os.User?.PushSubscription?.optedIn;
 stop.hidden=!subscribed;
 start.textContent=subscribed?"Save my topics":"Turn on notifications";
}
async function getConfiguration(){
 const r=await fetch("/api/onesignal-web-config",{headers:{Accept:"application/json"},cache:"no-store"});
 if(!r.ok)throw Error("Website notification settings are unavailable.");
 const j=await r.json();
 if(!j.configured||!/^[a-f0-9-]{36}$/i.test(j.appId||""))
   throw Error("Push alerts are not activated yet. You can still follow the news on Rochdale Daily.");
 appId=j.appId;
 return j;
}
function loadSDK(){
 if(sdkPromise)return sdkPromise;
 sdkPromise=new Promise(function(resolve,reject){
   if(window.OneSignalDeferred){resolve();return;}
   window.OneSignalDeferred=window.OneSignalDeferred||[];
   const script=document.createElement("script");
   script.async=true;
   script.src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js";
   script.onload=resolve;
   script.onerror=()=>reject(Error("Could not contact the notification service."));
   document.head.appendChild(script);
 });
 return sdkPromise;
}
function initialise(config){
 return new Promise(function(resolve,reject){
   window.OneSignalDeferred=window.OneSignalDeferred||[];
   window.OneSignalDeferred.push(async function(oneSignal){
     try{
       // Explicit permissions precede all provider state and subscription changes.
       oneSignal.setConsentRequired(true);
       oneSignal.setConsentGiven(true);
       await oneSignal.init({
         appId:config.appId,serviceWorkerPath:config.workerPath,
         serviceWorkerParam:{scope:config.scope},
         notifyButton:{enable:false},allowLocalhostAsSecureOrigin:false
       });
       os=oneSignal;
       resolve(oneSignal);
     }catch(err){reject(err);}
   });
 });
}
async function ensureReady(){
 if(os)return os;
 const config=await getConfiguration();
 await loadSDK();
 return initialise(config);
}
async function tags(oneSignal){
 const selectedTopics=selected();
 if(!selectedTopics.length)throw Error("Choose at least one news topic.");
 const payload={};
 for(const topic of categories)payload["rd_topic_"+topic]=selectedTopics.includes(topic)?"1":"0";
 // SDK's tag update applies only to a user who expressly opts into push.
 await oneSignal.User.addTags(payload);
}
function humanError(err){
 const message=String(err?.message||"Unexpected problem.");
 if(/denied|blocked|permission/i.test(message))
   return "Browser notifications are blocked. Enable them in browser settings, then try again.";
 return message;
}
form.addEventListener("submit",async function(ev){
 ev.preventDefault();
 if(!selected().length){tell("Please choose at least one topic.","error");return;}
 if(!("Notification" in window)||!("serviceWorker" in navigator)||!window.isSecureContext){
   tell("Web push is not available in this browser. On iPhone, add this site to your Home Screen and use it from there.","error");
   return;
 }
 start.disabled=true;tell("Connecting your chosen news alerts…","working");
 try{
   const client=await ensureReady();
   await tags(client);
   if(Notification.permission==="denied")throw Error("Permission denied.");
   if(!client.User.PushSubscription.optedIn){
     await client.Notifications.requestPermission();
     if(Notification.permission!=="granted")throw Error("Permission was not granted.");
     await client.User.PushSubscription.optIn();
   }
   if(!client.User.PushSubscription.optedIn)throw Error("Subscription was not completed.");
   tell("You're subscribed. Only the topics you've selected will be considered for alerts. You can change these or unsubscribe here.","ok");
   setButtons();
 }catch(e){tell(humanError(e),"error");}
 finally{start.disabled=false;}
});
stop.addEventListener("click",async function(){
 stop.disabled=true;tell("Switching off browser alerts…","working");
 try{
  const client=await ensureReady();
  await client.User.PushSubscription.optOut();
  // Withhold OneSignal consent after opting out; a future subscription needs
  // another deliberate click.
  client.setConsentGiven(false);
  os=null;sdkPromise=null;
  tell("Browser alerts are now off for this device.","ok");
  setButtons();
 }catch(e){tell(humanError(e),"error");}
 finally{stop.disabled=false;}
});
})();
