// Rochdale Daily: Mobile menu toggle (namespaced)
(function () {
  const toggle = document.querySelector('.rd-menu-toggle');
  const menu = document.getElementById('primary-menu');
  if (!toggle || !menu) return;

  function closeMenu() {
    menu.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  toggle.addEventListener('click', () => {
    const isOpen = menu.classList.toggle('open');
    toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    document.body.style.overflow = isOpen ? 'hidden' : '';
  });

  menu.addEventListener('click', (e) => {
    if (e.target.closest('a')) closeMenu();
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) closeMenu();
  });
})();


/* Opt-in Rochdale Daily sonic logo. Never autoplay or play on first touch. */
(() => {
  if (document.getElementById('rd-sound-toggle')) return;
  const button=document.createElement('button');
  button.id='rd-sound-toggle';
  button.type='button';
  button.setAttribute('aria-label','Play Rochdale Daily welcome chime');
  button.textContent='♪ Sound off';
  button.style.cssText='position:fixed;right:12px;bottom:12px;z-index:9000;border:1px solid #b9cbd2;border-radius:24px;background:#fff;color:#13394a;padding:9px 12px;font:600 12px system-ui;box-shadow:0 2px 10px #0002;cursor:pointer';
  let enabled=false;
  try {enabled=localStorage.getItem('rd_welcome_sound')==='yes';}catch(_){}
  button.textContent=enabled?'♪ Sound on':'♪ Sound off';
  let audio=null;
  function chime(){
    const AudioContext=window.AudioContext||window.webkitAudioContext;
    if(!AudioContext) return;
    try{
      audio=audio||new AudioContext();
      if(audio.state==='suspended') audio.resume();
      const start=audio.currentTime+0.02;
      [880,1174.66,1567.98].forEach((freq,index)=>{
        const oscillator=audio.createOscillator(),gain=audio.createGain();
        oscillator.type='sine';oscillator.frequency.value=freq;
        gain.gain.setValueAtTime(0.0001,start+index*0.12);
        gain.gain.exponentialRampToValueAtTime(0.065,start+index*0.12+0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001,start+index*0.12+0.55);
        oscillator.connect(gain).connect(audio.destination);
        oscillator.start(start+index*0.12);
        oscillator.stop(start+index*0.12+0.57);
      });
    }catch(_){}
  }
  window.RochdaleDailyChime = () => { if (enabled) chime(); };
  button.addEventListener('click',()=>{
    enabled=!enabled;
    try{localStorage.setItem('rd_welcome_sound',enabled?'yes':'no');}catch(_){}
    button.textContent=enabled?'♪ Sound on':'♪ Sound off';
    button.setAttribute('aria-label',enabled?'Turn off Rochdale Daily chime':'Turn on Rochdale Daily chime');
    if(enabled)chime();
  });
  document.body.appendChild(button);
  // Sit above the cookie bar while it is open: at 12px from the bottom the
  // pill covered the bar's "Accept all" button on phones (28 Oct 2026).
  function place(){
    const bar=document.querySelector('.cookie.show');
    button.style.bottom=bar?(bar.offsetHeight+12)+'px':'12px';
  }
  place();
  try{new MutationObserver(place).observe(document.body,{subtree:true,attributes:true,attributeFilter:['class'],childList:true});}catch(_){}
  window.addEventListener('resize',place);
})();

/* Shared newsletter controller, including previously generated article pages.
 * Capture prevents older inline handlers from issuing a duplicate signup.
 */
(() => {
 const forms=[...document.querySelectorAll('form')].filter(f=>/^(newsletter|rail-newsletter|article-newsletter)-form$/.test(f.id));
 for(const form of forms){
  const prefix=form.id.replace(/-form$/, "");
  if(!form.querySelector('[name="consent"]')){
   const label=document.createElement('label');label.className='newsletter-consent';
   const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.name='consent';checkbox.required=true;
   checkbox.id=prefix+'-consent';label.append(checkbox,document.createTextNode('Send me the Rochdale Daily newsletter. I can unsubscribe at any time.'));
   form.querySelector('button[type="submit"]')?.before(label);
  }
  if(!form.querySelector('[name="website"]')){
   const trap=document.createElement('input');trap.name='website';trap.type='text';trap.tabIndex=-1;trap.autocomplete='off';trap.hidden=true;form.append(trap);
  }
 }
 document.addEventListener('submit',async event=>{
  const form=event.target;if(!forms.includes(form))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(form.dataset.submitting==='yes')return;
  const prefix=form.id.replace(/-form$/, ""),status=document.getElementById(prefix+'-status');
  const emailInput=form.querySelector('[name="email"]'),consent=form.querySelector('[name="consent"]');
  if(!emailInput||!status)return;
  const email=emailInput.value.trim();
  if(email.length>254||!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)){
   status.textContent='Please enter a valid email address.';emailInput.focus();return;
  }
  if(!consent?.checked){status.textContent='Please tick the box to receive the newsletter.';consent?.focus();return;}
  const button=form.querySelector('button[type="submit"]'),controller=new AbortController();
  form.dataset.submitting='yes';if(button)button.disabled=true;form.setAttribute('aria-busy','true');
  status.textContent='Saving your signup…';
  const timeout=setTimeout(()=>controller.abort(),15000);
  try{
   const response=await fetch('/api/newsletter',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
    body:JSON.stringify({email,consent:true,website:form.querySelector('[name="website"]')?.value||'',source:prefix})});
   const data=await response.json();
   if(!response.ok||data.ok!==true)throw Error(data.error||'Signup could not be saved. Please try again.');
   status.textContent=data.message||'Your newsletter signup has been saved.';form.reset();
   if(typeof CustomEvent==='function'&&document.dispatchEvent)document.dispatchEvent(new CustomEvent('rd:newsletter-saved'));
  }catch(error){status.textContent=error.name==='AbortError'?'The request timed out. Your signup may have been saved; it is safe to try again.':error.message||'Could not connect. Please try again.';}
  finally{clearTimeout(timeout);delete form.dataset.submitting;form.setAttribute('aria-busy','false');if(button)button.disabled=false;}
 },true);
})();

/* Visible reporting standards and useful participation links on every article. */
(() => {
 const byline=document.querySelector('.article-byline');if(!byline||document.getElementById('rd-reporting-links'))return;
 const nav=document.createElement('nav');nav.id='rd-reporting-links';nav.setAttribute('aria-label','Reporting standards and discussion');
 nav.style.cssText='display:flex;flex-wrap:wrap;gap:10px 18px;margin:14px 0 22px;padding:12px 0;border-top:1px solid #d9e4e8;border-bottom:1px solid #d9e4e8;font:700 12px/1.5 system-ui';
 const sources=document.querySelector('.article-sources');if(sources&&!sources.id)sources.id='rd-article-sources';
 const records=[['How we report','/editorial-standards'],['Corrections and right of reply','/corrections-and-complaints'],['Explore My Rochdale','/my-rochdale']];
 if(sources)records.unshift(['Read the sources','#'+sources.id]);
 if(document.getElementById('comments-root'))records.push(['Have your say','#comments-root']);
 for(const [text,href] of records){const a=document.createElement('a');a.textContent=text;a.href=href;a.style.color='#136c76';
  if(sources&&href==='#'+sources.id)a.addEventListener('click',()=>{sources.open=true;});nav.append(a);}
 byline.after(nav);
})();

