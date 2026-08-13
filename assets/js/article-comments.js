(() => {
  const root = document.getElementById('comments-root');
  if (!root) return;

  const API = '/api/comments';
  const MAX = 1500;
  const slug = root.dataset.slug || '';
  const category = (root.dataset.category || '').toLowerCase();
  let session = null;
  try { session = JSON.parse(localStorage.getItem('rd_comment_session') || 'null'); } catch (_) {}

  const css = `
    .comments-section{margin-top:18px;padding:22px;border:2px solid #8bdce8;border-radius:12px;background:linear-gradient(180deg,#f0fcfe 0,#fff 170px);box-shadow:0 8px 24px rgba(14,116,144,.09)}
    .comments-section h2{font-family:"Roboto Condensed",Arial,sans-serif;text-transform:uppercase;font-size:25px;margin:0 0 4px;color:#123743}
    .comments-invite{margin:0 0 18px;padding:14px 16px;background:#dff8fc;border-left:5px solid #0e7490;border-radius:0 8px 8px 0}
    .comments-invite strong{display:block;font-family:"Roboto Condensed",Arial,sans-serif;font-size:18px;color:#0b5265;margin-bottom:3px}.comments-invite span{font-size:14px;color:#334e57}
    .comments-note{color:#5f6b78;font-size:13px;margin:0 0 18px}
    .comments-closed,.comment-auth{background:#f2f2f2;border:1px solid #d8d8d8;padding:16px;font-size:14px}
    .comment{background:#fff;border:1px solid #cbdde1;padding:14px 16px;margin-bottom:12px;display:flex;gap:14px;border-radius:7px}
    .comment-main{flex:1;min-width:0}.comment-user{font-weight:900;color:#0e7490;font-size:13px;text-transform:uppercase;letter-spacing:.5px}
    .comment-time{color:#666;font-size:12px;margin-left:8px;font-weight:400;text-transform:none;letter-spacing:0}
    .comment-body{margin:6px 0 0;font-size:15px;line-height:1.5;overflow-wrap:anywhere}
    .comment-form textarea,.comment-auth input{width:100%;background:#fff;border:1px solid #9dbcc3;color:#202020;padding:11px;font:inherit;font-size:16px;border-radius:5px}
    .comment-form textarea{min-height:110px;resize:vertical}.comment-auth input{margin-bottom:9px}
    .comment-form .rowline{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:8px}
    .comment-chars{color:#666;font-size:12px}.comment-submit{background:#22d3ee;color:#0b1524;border:2px solid #0b1524;padding:11px 20px;font-weight:900;text-transform:uppercase;cursor:pointer;border-radius:4px}
    .comment-submit:disabled{opacity:.55}.comment-auth .tabs{display:flex;gap:8px;margin-bottom:12px}.comment-auth .tabs button{flex:1;background:#fff;border:1px solid #bbb;padding:10px;font-weight:900;text-transform:uppercase}
    .comment-auth .tabs button.on{background:#0e7490;color:#fff}.comment-msg{margin:10px 0 0;font-size:13px;padding:9px 11px;display:none}.comment-msg.err,.comment-msg.ok{display:block}.comment-msg.err{background:#fbeaec;border-left:4px solid #c8102e}.comment-msg.ok{background:#e7f7ef;border-left:4px solid #23a06a}
    .comment-signedin{display:flex;justify-content:space-between;align-items:center;gap:12px;color:#666;font-size:13px;margin-bottom:10px}.comment-signout,.comment-report{background:none;border:0;color:#666;text-decoration:underline;cursor:pointer;padding:0}
    .upvote{display:flex;flex-direction:column;align-items:center;gap:2px;background:none;border:0;padding:4px 2px;cursor:pointer;color:#666;min-width:42px}.upvote svg{width:24px;height:24px;stroke:currentColor;stroke-width:2.4;fill:none}.upvote.voted{color:#0e7490}.upvote-count{font-size:13px;font-weight:900}
    @media(max-width:600px){.comments-section{margin-top:14px;padding:17px 13px}.comments-invite{padding:12px}.comment{padding:12px 10px;gap:8px}.comment-auth{padding:13px}.comment-form .rowline{align-items:stretch;flex-direction:column}.comment-submit{width:100%;min-height:46px}.comment-signedin{align-items:flex-start}.comments-section h2{font-size:23px}}
  `;
  const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);

  const esc = value => String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  const save = value => { session = value; try { value ? localStorage.setItem('rd_comment_session', JSON.stringify(value)) : localStorage.removeItem('rd_comment_session'); } catch (_) {} };
  const ago = iso => { const t = new Date(iso).getTime(); if (!Number.isFinite(t)) return ''; const m = Math.max(0, Math.round((Date.now()-t)/60000)); if (m<1) return 'just now'; if (m<60) return `${m} minute${m===1?'':'s'} ago`; const h=Math.round(m/60); if(h<24)return `${h} hour${h===1?'':'s'} ago`; const d=Math.round(h/24); return `${d} day${d===1?'':'s'} ago`; };
  async function api(payload){ const r=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); let data={}; try{data=await r.json();}catch(_){} return {ok:r.ok,data}; }
  const message=(text,kind)=>{const el=document.getElementById('comment-msg');if(!el)return;el.textContent=text;el.className=`comment-msg ${kind}`;};

  function storyQuestion(){
    const questions={
      traffic:['How is this affecting you?','Tell other local readers what you are seeing on the roads or how your journey has been affected.'],
      transport:['Do you use this route?','Tell us how this change affects your journey and what other passengers should know.'],
      politics:['What do you think?','How do you think this decision or development will affect people locally?'],
      education:['What is your experience?','Parents, pupils, students and staff can share useful local experience below.'],
      business:['What does this mean locally?','Have you used this business or noticed the change? Share your local perspective.'],
      community:['Have your say','Does this affect your neighbourhood or community? Tell us what you think.'],
      health:['What is your local experience?','Share your view or experience without posting private medical information.'],
      environment:['What are you seeing locally?','Tell us how this issue affects your area and what you think should happen next.'],
      sport:['What did you make of it?','Supporters and local sports followers — share your view below.'],
      events:['Are you going?','Tell other readers what you are looking forward to, or share your experience if you have been.'],
      news:['What do you think?','Share your local knowledge, experience or view with other Rochdale Daily readers.']
    };
    return questions[category] || questions.news;
  }

  function commentMarkup(c){
    const mine=session&&session.username&&session.username.toLowerCase()===String(c.username||'').toLowerCase();
    return `<article class="comment" data-comment="${esc(c.id)}"><button class="upvote${c.likedByMe?' voted':''}" data-upvote="${esc(c.id)}" ${mine?'disabled':''} aria-label="Upvote"><svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="5,15 12,8 19,15"></polyline></svg><span class="upvote-count">${Number(c.likeCount||0)}</span></button><div class="comment-main"><div class="comment-user">${esc(c.username)}<span class="comment-time">${esc(ago(c.postedAt))}</span></div><p class="comment-body">${esc(c.body)}</p><button class="comment-report" data-report="${esc(c.id)}">Report</button></div></article>`;
  }

  function renderCompose(){
    const host=document.getElementById('comment-compose'); if(!host)return;
    if(session){
      host.innerHTML=`<div class="comment-signedin"><span>Commenting as <strong>${esc(session.username)}</strong></span><button class="comment-signout" id="comment-signout" type="button">Sign out</button></div><div class="comment-form"><label for="comment-body">Join the conversation</label><textarea id="comment-body" maxlength="${MAX}" placeholder="Share your view or local knowledge"></textarea><div class="rowline"><span class="comment-chars" id="comment-chars">0 / ${MAX}</span><button class="comment-submit" id="comment-post" type="button">Post comment</button></div><p class="comment-msg" id="comment-msg" role="status"></p></div>`;
    } else {
      host.innerHTML=`<div class="comment-auth"><div class="tabs"><button type="button" id="tab-in" class="on">Sign in</button><button type="button" id="tab-up">Create account</button></div><div id="auth-fields"><label for="auth-user">Username</label><input id="auth-user" autocomplete="username" placeholder="Username"><label for="auth-pass">Password</label><input id="auth-pass" type="password" autocomplete="current-password" placeholder="Password"><button class="comment-submit" id="auth-go" type="button" style="width:100%">Sign in to join the conversation</button><p class="comment-msg" id="comment-msg" role="status"></p></div></div>`;
    }
    wire();
  }

  function wire(){
    document.getElementById('comment-signout')?.addEventListener('click',()=>{save(null);mount();});
    const box=document.getElementById('comment-body'), chars=document.getElementById('comment-chars');
    box?.addEventListener('input',()=>{if(chars)chars.textContent=`${box.value.length} / ${MAX}`;});
    document.getElementById('comment-post')?.addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;const {ok,data}=await api({action:'comment',token:session.token,slug,body:box.value});b.disabled=false;if(!ok){message((data.errors||[data.error||'That did not work.']).join(' '),'err');return;}box.value='';mount();});
    let mode='login'; const tabIn=document.getElementById('tab-in'),tabUp=document.getElementById('tab-up'),fields=document.getElementById('auth-fields');
    const draw=()=>{if(!fields)return;fields.innerHTML=`<label for="auth-user">Username</label><input id="auth-user" autocomplete="username" placeholder="Username">${mode==='register'?'<label for="auth-email">Email</label><input id="auth-email" type="email" autocomplete="email" placeholder="Email (never shown publicly)">':''}<label for="auth-pass">Password</label><input id="auth-pass" type="password" autocomplete="current-password" placeholder="Password"><button class="comment-submit" id="auth-go" type="button" style="width:100%">${mode==='register'?'Create account and join in':'Sign in to join in'}</button><p class="comment-msg" id="comment-msg" role="status"></p>`;document.getElementById('auth-go').addEventListener('click',auth);};
    const auth=async e=>{const b=e.currentTarget;b.disabled=true;const payload={action:mode,username:document.getElementById('auth-user').value,password:document.getElementById('auth-pass').value};if(mode==='register')payload.email=document.getElementById('auth-email').value;const {ok,data}=await api(payload);b.disabled=false;if(!ok){message((data.errors||[data.error||'That did not work.']).join(' '),'err');return;}save({token:data.token,username:data.username});mount();};
    tabIn?.addEventListener('click',()=>{mode='login';tabIn.classList.add('on');tabUp.classList.remove('on');draw();});tabUp?.addEventListener('click',()=>{mode='register';tabUp.classList.add('on');tabIn.classList.remove('on');draw();});if(fields)draw();
    root.querySelectorAll('[data-upvote]').forEach(btn=>btn.addEventListener('click',async()=>{if(!session){message('Sign in to upvote comments.','err');return;}const {ok}=await api({action:'upvote',token:session.token,commentId:btn.dataset.upvote});if(ok)mount();}));
    root.querySelectorAll('[data-report]').forEach(btn=>btn.addEventListener('click',async()=>{const reason=prompt('Briefly say why this comment should be reviewed:');if(!reason)return;await api({action:'report',token:session&&session.token,commentId:btn.dataset.report,reason});alert('Thank you. The comment has been reported.');}));
  }

  async function mount(){
    root.innerHTML='<h2>Comments</h2><p class="comments-note">Loading…</p>';
    let payload={}; try{const headers={Accept:'application/json'};if(session)headers['x-session-token']=session.token;const r=await fetch(`${API}?slug=${encodeURIComponent(slug)}`,{headers});payload=await r.json();}catch(_){root.innerHTML='<h2>Comments</h2><p class="comments-note">Comments are unavailable just now.</p>';return;}
    if(payload.closed||category==='crime'){root.innerHTML=`<h2>Comments</h2><div class="comments-closed"><strong>${esc(payload.closedReason||'Comments are closed on this article.')}</strong></div>`;return;}
    const comments=Array.isArray(payload.comments)?payload.comments:[];
    const question=storyQuestion();
    root.innerHTML=`<h2>Join the conversation <span style="font-size:.7em;color:#52717a">(${comments.length})</span></h2><div class="comments-invite"><strong>${esc(question[0])}</strong><span>${esc(question[1])}</span></div><p class="comments-note">Be civil, stick to the story, and remember real people live here. Comments are published straight away.</p><div id="comment-compose"></div><div id="comment-list">${comments.map(commentMarkup).join('')||'<p class="comments-note"><strong>No comments yet.</strong> Be the first Rochdale Daily reader to join the conversation.</p>'}</div>`;
    renderCompose();
  }
  mount();
})();