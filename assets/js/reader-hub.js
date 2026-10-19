/* Read-only discovery. Optional preferences never contain an email or postcode. */
(() => {
 'use strict';
 const form=document.getElementById('reader-preferences');if(!form)return;
 const area=document.getElementById('reader-area'),topic=document.getElementById('reader-topic'),status=document.getElementById('reader-status'),list=document.getElementById('reader-stories');
 let stories=[];const key='rd_reader_choices_v1';
 function apply(value){for(const [select,v] of [[area,value.area],[topic,value.topic]])if([...select.options].some(o=>o.value===v))select.value=v;}
 try{apply(JSON.parse(localStorage.getItem(key)||'{}'));}catch(_){}
 const params=new URLSearchParams(location.search);apply({area:params.get('area')||area.value,topic:params.get('topic')||topic.value});
 function stamp(item){return Date.parse(item.first_published_at||item.published_at||'')||0;}
 function url(item){const slug=String(item.slug||'');return /^[a-z0-9-]+$/.test(slug)?'/articles/'+slug:null;}
 function show(){
  list.replaceChildren();const selected=stories.filter(item=>(!area.value||String(item.area||'').toLowerCase()===area.value.toLowerCase())&&(!topic.value||String(item.category||'').toLowerCase()===topic.value)).slice(0,12);
  for(const item of selected){const li=document.createElement('li'),h=document.createElement('h3'),a=document.createElement('a'),meta=document.createElement('p'),summary=document.createElement('p');a.href=url(item);a.textContent=item.title;h.append(a);meta.className='meta';meta.textContent=[item.area,item.category,new Date(stamp(item)).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})].filter(Boolean).join(' · ');summary.textContent=String(item.excerpt||item.summary||'').replace(/<[^>]*>/g,'').slice(0,350);li.append(meta,h,summary);list.append(li);}
  status.textContent=selected.length?'Showing '+selected.length+' recent reports. Dates identify when each story was published.':'No recent reports match both choices. Try all subjects or another area, or browse the archive.';
 }
 form.addEventListener('submit',event=>{event.preventDefault();show();const query=new URLSearchParams();if(area.value)query.set('area',area.value);if(topic.value)query.set('topic',topic.value);history.replaceState(null,'',location.pathname+(query.size?'?'+query:''));});
 document.getElementById('reader-save').addEventListener('click',()=>{try{localStorage.setItem(key,JSON.stringify({area:area.value,topic:topic.value}));show();status.textContent+=' Choices saved on this device.';}catch(_){status.textContent='This browser could not save choices. You can still use the filters.';}});
 document.getElementById('reader-clear').addEventListener('click',()=>{try{localStorage.removeItem(key);}catch(_){}area.value='';topic.value='';history.replaceState(null,'',location.pathname);show();status.textContent+=' Saved choices removed.';});
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
 fetch('/articles.json',{signal:controller.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
  const now=Date.now();stories=(Array.isArray(data)?data:Array.isArray(data.articles)?data.articles:[]).filter(item=>item&&item.title&&url(item)&&String(item.status||'published').toLowerCase()==='published'&&!item.requires_approval&&!item.sponsored&&!item.paid_submission&&stamp(item)>0&&stamp(item)<=now).sort((a,b)=>stamp(b)-stamp(a));
  const briefing=stories.find(item=>item.briefing_slot==='morning'||/^morning briefing\b/i.test(item.title));if(briefing){const sample=document.getElementById('reader-sample');sample.href=url(briefing);sample.textContent='Read the briefing published '+new Date(stamp(briefing)).toLocaleDateString('en-GB');}show();
 }).catch(()=>{status.textContent='Recent stories could not load. Use the ward pages or archive below.';}).finally(()=>clearTimeout(timeout));
 const delivery=document.getElementById('reader-delivery');
 fetch('/api/reader-integrations').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{delivery.textContent=data.newsletter?.providerConfigured?'Email delivery is configured. Sending depends on a verified briefing and the delivery service.':'Email delivery is being set up. You can save a signup, but newsletters are not being sent yet.';}).catch(()=>{delivery.textContent='Email delivery status could not be checked. The signup response will confirm what was saved.';});
})();
