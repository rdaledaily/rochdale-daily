/* Shared reader journeys and consent-respecting measurement. No personal fields. */
(() => {
 'use strict';
 function track(name,slot){if(typeof window.rdCookieConsent!=='function'||!window.rdCookieConsent()||typeof window.gtag!=='function')return;window.gtag('event',name,{reader_slot:slot,transport_type:'beacon'});}
 const nav=document.querySelector('.primary-nav .nav-list');
 if(nav&&!nav.querySelector('a[href="/start-here.html"]')){const li=document.createElement('li'),a=document.createElement('a');a.href='/start-here.html';a.textContent='Your briefing';li.append(a);nav.append(li);}
 const article=document.querySelector('.article-main');
 if(article){
  const copy=article.querySelector('.article-copy'),date=Date.parse(document.querySelector('meta[property="article:published_time"]')?.content||'');
  if(copy&&Number.isFinite(date)&&Date.now()-date>30*86400000&&!document.getElementById('reader-archive-note')){const note=document.createElement('p');note.id='reader-archive-note';note.className='reader-archive-note';note.textContent='From the archive: this report was published '+new Date(date).toLocaleDateString('en-GB')+'. Arrangements may have changed; check the dated sources before acting.';copy.before(note);}
  const headings=copy?[...copy.querySelectorAll('h2')].filter(h=>!h.closest('.article-sources')):[];
  if(headings.length>=3&&!document.getElementById('reader-contents')){const details=document.createElement('details'),summary=document.createElement('summary'),list=document.createElement('ul');details.id='reader-contents';details.className='reader-contents';summary.textContent='In this report';for(const [i,h]of headings.entries()){if(!h.id)h.id='reader-section-'+i;const li=document.createElement('li'),a=document.createElement('a');a.href='#'+h.id;a.textContent=h.textContent;li.append(a);list.append(li);}details.append(summary,list);copy.before(details);}
 }
 if(article&&!document.getElementById('reader-return')){
  const section=document.createElement('section');section.id='reader-return';section.className='reader-return';section.setAttribute('aria-labelledby','reader-return-title');
  const h=document.createElement('h2');h.id='reader-return-title';h.textContent='Keep following your borough';const p=document.createElement('p');p.textContent='Choose your area, read the morning briefing or send us a question for a future report.';
  const a=document.createElement('a');a.href='/start-here.html';a.textContent='Find your local news and briefing';const tip=document.createElement('a');tip.href='mailto:news@rochdaledaily.co.uk?subject=Reader%20question';tip.textContent='Ask the newsdesk';section.append(h,p,a,tip);
  const anchor=article.querySelector('.read-next')||article.querySelector('.article-copy');if(anchor)anchor.after(section);
 }
 document.addEventListener('click',event=>{const a=event.target.closest('a,button');if(!a)return;let slot;if(a.closest('.read-next,.next-bar,.rd-read-next-prompt'))slot='related_story';else if(a.closest('.article-sources'))slot='source';else if(a.closest('#reader-return'))slot='return_options';else if(a.getAttribute('href')==='/start-here.html')slot='briefing_navigation';if(slot)track('reader_journey_click',slot);});
 document.addEventListener('rd:newsletter-saved',()=>track('newsletter_signup_saved','newsletter'));
 if(article){let reported=false,visible=false,timer;const copy=article.querySelector('.article-copy');if(copy&&'IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>{visible=entries.some(e=>e.isIntersecting);clearTimeout(timer);if(visible)timer=setTimeout(()=>{if(!reported&&visible&&document.visibilityState==='visible'&&window.rdCookieConsent?.()){reported=true;track('article_copy_reached','article');observer.disconnect();}},10000);});document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='visible'){visible=false;clearTimeout(timer);}});const last=copy.querySelector('p:last-of-type');if(last)observer.observe(last);}}
})();
