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
  button.addEventListener('click',()=>{
    enabled=!enabled;
    try{localStorage.setItem('rd_welcome_sound',enabled?'yes':'no');}catch(_){}
    button.textContent=enabled?'♪ Sound on':'♪ Sound off';
    button.setAttribute('aria-label',enabled?'Turn off Rochdale Daily chime':'Turn on Rochdale Daily chime');
    if(enabled)chime();
  });
  document.body.appendChild(button);
})();
