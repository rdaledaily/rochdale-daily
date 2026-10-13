/* Reader-controlled breaking-news browser notifications.
 * No SDK, cookie or permission prompt before a direct button click.
 * The site's existing in-page story alerts work without any push account.
 */
(() => {
"use strict";
const mount=document.querySelector(".edition-links");
if(!mount||!("Notification" in window)||!("serviceWorker" in navigator))return;
fetch("/api/reader-integrations",{cache:"no-store"}).then(x=>x.ok?x.json():null).then(data=>{
 const id=data?.webPush?.appId;
 if(!/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(String(id||"")))return;
 const button=document.createElement("button");
 button.type="button";button.className="rd-push-optin";
 button.textContent=Notification.permission==="granted"?"Manage news alerts":"Get breaking news alerts";
 button.setAttribute("aria-label","Opt into Rochdale Daily breaking news web notifications");
 const style=document.createElement("style");
 style.textContent=".rd-push-optin{border:1px solid #92b9be;background:#10283b;color:#fff;border-radius:5px;font:750 12px system-ui;min-height:38px;padding:8px 12px;cursor:pointer}.rd-push-optin:hover{background:#136c76}.rd-push-optin:focus-visible{outline:3px solid #2c9dac;outline-offset:2px}";
 document.head.append(style);mount.append(button);
 let loaded=false;
 button.addEventListener("click",()=>{
   if(loaded)return;
   loaded=true;button.disabled=true;button.textContent="Opening notification settings…";
   window.OneSignalDeferred=window.OneSignalDeferred||[];
   window.OneSignalDeferred.push(async OneSignal=>{
    try{
      await OneSignal.init({appId:id,notifyButton:{enable:false},serviceWorkerPath:"/OneSignalSDKWorker.js"});
      await OneSignal.Notifications.requestPermission();
      button.textContent=OneSignal.Notifications.permission?"News notifications enabled":"News alerts are optional";
    }catch{button.textContent="Unable to enable news alerts";loaded=false;}
    finally{button.disabled=false;}
   });
   const sdk=document.createElement("script");sdk.src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js";sdk.async=true;
   sdk.onerror=()=>{loaded=false;button.disabled=false;button.textContent="Alerts unavailable: try again later";};
   document.head.append(sdk);
 });
}).catch(()=>{ /* Never impede the newspaper if the integration is offline. */ });
})();