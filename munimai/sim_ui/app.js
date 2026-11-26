/* SaralcreditAI front end. Plain JavaScript, no build step. Sections: helpers, routing, chat and voice, side panel, close the month, insights. */
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const MAX_MB=15;
let lang=localStorage.getItem('munim_lang')||'kn';
let state='idle',ctl=null,player=null,clipQ=[],clipsDone=true,levelRAF=0,curQ='',lastLang='en',hold=false;
let munimId=localStorage.getItem('munim_id');
if(!munimId){munimId=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random().toString(16).slice(2));localStorage.setItem('munim_id',munimId);}
const H={'X-Munim-Id':munimId};
const JH={...H,'Content-Type':'application/json'};
const t=k=>(T[lang]&&T[lang][k]!=null)?T[lang][k]:T.en[k];
const icons=()=>window.lucide&&lucide.createIcons();
const feed=$('feed'),col=$('col'),msg=$('msg'),orb=$('orb');
const api=async(path,opt={})=>{const r=await fetch(path,opt);if(!r.ok)throw new Error('HTTP '+r.status);return r.json();};
const post=(path,body)=>api(path,{method:'POST',headers:JH,body:JSON.stringify(body||{})});
const money=n=>'₹'+Math.round(n).toLocaleString('en-IN');
const rupees=p=>money((p||0)/100);

/* ---------- toasts, dialogs ---------- */
function toast(text,kind){
  const el=document.createElement('div');el.className='toast';el.innerHTML='<i data-lucide="'+(kind==='err'?'circle-alert':'circle-check')+'"></i><span>'+esc(text)+'</span>';
  $('toasts').appendChild(el);icons();setTimeout(()=>el.remove(),3800);
}
let dlgOpener=null;
function focusables(root){return [...root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])')].filter(e=>e.offsetParent!==null);}
function openDlg(el,focusEl){
  dlgOpener=document.activeElement;el.classList.add('on');
  setTimeout(()=>(focusEl||focusables(el)[0]||el).focus(),30);
}
function closeDlg(el){el.classList.remove('on');if(dlgOpener&&dlgOpener.focus)dlgOpener.focus();dlgOpener=null;}
document.addEventListener('keydown',e=>{
  const open=document.querySelector('.scrim.on');if(!open)return;
  if(e.key==='Escape'){closeDlg(open);return;}
  if(e.key==='Tab'){const f=focusables(open);if(!f.length)return;const a=f[0],b=f[f.length-1];
    if(e.shiftKey&&document.activeElement===a){e.preventDefault();b.focus();}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a.focus();}}
});
function confirmBox(title,text,go){
  return new Promise(res=>{
    $('cfmH').textContent=title;$('cfmP').textContent=text;$('cfmNo').textContent=t('cancel');$('cfmYes').textContent=go;
    const done=v=>{closeDlg($('cfm'));$('cfmNo').onclick=$('cfmYes').onclick=null;res(v);};
    $('cfmNo').onclick=()=>done(false);$('cfmYes').onclick=()=>done(true);openDlg($('cfm'),$('cfmNo'));
  });
}

/* ---------- theme ---------- */
function applyTheme(th){
  if(th)document.documentElement.setAttribute('data-theme',th);else document.documentElement.removeAttribute('data-theme');
  const dark=th==='dark'||(!th&&matchMedia('(prefers-color-scheme:dark)').matches);
  $('themeBtn').innerHTML='<i data-lucide="'+(dark?'sun':'moon')+'"></i>';icons();
}
$('themeBtn').onclick=()=>{const dark=document.documentElement.getAttribute('data-theme')==='dark'||(!document.documentElement.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme:dark)').matches);
  const n=dark?'light':'dark';localStorage.setItem('munim_theme',n);applyTheme(n);};

/* ---------- language ---------- */
function setLang(l){
  lang=l;localStorage.setItem('munim_lang',l);document.documentElement.lang=l;
  document.querySelectorAll('.seg button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.l===l));
  document.querySelectorAll('[data-i]').forEach(e=>{e.textContent=t(e.dataset.i);});
  msg.placeholder=t('ph');$('convLbl').textContent=t('convS');$('convLbl').parentElement.title=t('conv');$('reviewLbl').textContent=t('review');
  $('dropT').innerHTML=esc(t('drop'))+'<small>'+esc(t('dropS'))+'</small>';
  $('setupH').textContent=t('sH');$('setupP').textContent=t('sP');$('bNameL').textContent=t('sN');$('bGstL').textContent=t('sG');$('bGstH').textContent=t('sGH');
  $('setupSave').textContent=t('save');$('setupSkip').textContent=t('skip');
  if(state==='idle')status(esc(t('say')));
  if(!col.querySelector('.msg'))renderWelcome();
  if(route==='close')renderClose();if(route==='insights')renderInsights();
}
document.querySelectorAll('.seg button').forEach(b=>b.onclick=()=>setLang(b.dataset.l));

/* ---------- routing ---------- */
let route='chat';
function setRoute(r,push){
  if(r==='panel'){$('side').classList.toggle('open');return;}
  if(!['chat','close','insights'].includes(r))r='chat';
  route=r;$('app').dataset.route=r;
  const ids={chat:'v-chat',close:'v-close',insights:'v-ins'};
  Object.entries(ids).forEach(([k,id])=>$(id).classList.toggle('on',k===r));
  document.querySelectorAll('#tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.route===r));
  document.querySelectorAll('#bnav button').forEach(b=>{if(b.dataset.route===r)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('side').classList.remove('open');
  if(push!==false&&location.hash!=='#'+r)history.replaceState(null,'','#'+r);
  if(r==='close')loadClose();if(r==='insights')loadInsights();
  document.title='SaralcreditAI · '+({chat:t('nChat'),close:t('nClose'),insights:t('nIns')}[r]);
}
document.querySelectorAll('#tabs button,#bnav button').forEach(b=>b.onclick=()=>setRoute(b.dataset.route));
addEventListener('hashchange',()=>setRoute(location.hash.slice(1),false));
document.querySelectorAll('#ptabs button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#ptabs button').forEach(x=>x.setAttribute('aria-selected',x===b));
  document.querySelectorAll('.pane').forEach(p=>p.classList.toggle('on',p.id==='p-'+b.dataset.p));
  if(b.dataset.p==='plan')loadPlan();
  if(b.dataset.p==='trace')loadSystem();
});
$('sideBtn').onclick=()=>$('side').classList.toggle('open');

/* ---------- chat: state and steps ---------- */
function status(html){$('status').innerHTML=html||'';}
function setState(s,line){
  state=s;orb.dataset.s=s;orb.setAttribute('aria-label',s==='idle'?'Speak':'Stop');
  const ic={idle:'mic',listening:'mic',thinking:'loader-circle',speaking:'volume-2'}[s];
  orb.innerHTML='<i data-lucide="'+ic+'"></i>';icons();
  status(line||(s==='idle'?esc(t('say')):s==='listening'?esc(t('listen')):s==='thinking'?'<span class="dots"><i></i><i></i><i></i></span> '+esc(t('think')):esc(t('speak'))));
}
const dropWelcome=()=>{const h=col.querySelector('.welcome');if(h)h.remove();};
function add(side,html,cls=''){dropWelcome();const m=document.createElement('div');m.className='msg '+side;m.innerHTML='<div class="bubble '+cls+'">'+html+'</div>';col.appendChild(m);feed.scrollTop=feed.scrollHeight;icons();return m.firstChild;}
function renderWelcome(){
  col.innerHTML=`<div class="welcome"><div class="hero"><h1>${esc(t('hello'))}</h1><p>${esc(t('sub'))}</p></div>
   <div class="tasks">
    <button class="task" id="tk1"><span class="ic"><i data-lucide="mic"></i></span><b>${esc(t('c1t'))}</b><span>${esc(t('c1d'))}</span></button>
    <button class="task" id="tk2"><span class="ic"><i data-lucide="receipt-text"></i></span><b>${esc(t('c2t'))}</b><span>${esc(t('c2d'))}</span></button>
    <button class="task" id="tk3"><span class="ic"><i data-lucide="calendar-check"></i></span><b>${esc(t('c3t'))}</b><span>${esc(t('c3d'))}</span></button></div>
   <div class="ideas">${t('ideas').map(q=>`<button class="idea"><i data-lucide="message-circle"></i><span>${esc(q)}</span></button>`).join('')}</div></div>`;
  col.querySelectorAll('.idea').forEach(b=>b.onclick=()=>sendText(b.querySelector('span').textContent));
  $('tk1').onclick=()=>listen();$('tk2').onclick=()=>$('file').click();$('tk3').onclick=()=>setRoute('close');icons();
}
let stepT0=0,curStep=null;
function stepsReset(){stepT0=performance.now();curStep=null;$('steps').innerHTML='';}
function markDone(c,now){c.li.className='done';c.li.querySelector('.tick').innerHTML='<i data-lucide="check"></i>';c.li.querySelector('time').textContent=((now-c.t)/1000).toFixed(1)+'s';}
function stepNow(id,label){
  const ol=$('steps'),now=performance.now();if(curStep)markDone(curStep,now);
  const li=document.createElement('li');li.className='now';li.innerHTML='<span class="tick"></span>'+esc(label)+'<time></time>';ol.appendChild(li);curStep={li,t:now};icons();
}
function stepsEnd(){if(curStep){markDone(curStep,performance.now());curStep=null;icons();}}

/* ---------- chat: one live turn, streamed ---------- */
async function turn({text,blob,userBubble}){
  hold=false;stopSpeaking();if(ctl)ctl.abort();ctl=new AbortController();stepsReset();setState('thinking');curQ=text||'';
  const fd=new FormData();fd.append('language',blob?lang:'auto');fd.append('speak','1');if(blob)fd.append('file',blob,'voice.webm');else fd.append('text',text);
  let replyBubble=null,gotReply=false;
  const wait=add('them','<span class="live"><span class="dots"><i></i><i></i><i></i></span></span>');
  try{
    const r=await fetch('/sim/chat',{method:'POST',body:fd,headers:H,signal:ctl.signal});
    if(!r.ok||!r.body)throw new Error('HTTP '+r.status);
    const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
    for(;;){
      const {value,done}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n\n'))>=0){const blk=buf.slice(0,i);buf=buf.slice(i+2);
        const ev=/^event: (.*)$/m.exec(blk),da=/^data: (.*)$/m.exec(blk);if(!ev||!da)continue;
        const d=JSON.parse(da[1]);
        if(ev[1]==='stage'){stepNow(d.id,d.label);if(d.id==='speaking')setState('thinking');}
        else if(ev[1]==='heard'){curQ=d.text;if(userBubble)userBubble.insertAdjacentHTML('beforeend','<div class="heard">“'+esc(d.text)+'”</div>');}
        else if(ev[1]==='reply'){gotReply=true;wait.parentElement.remove();replyBubble=showReply(d);}
        else if(ev[1]==='clip'){enqueue(d.b64);}
        else if(ev[1]==='fail'){wait.parentElement&&wait.parentElement.remove();add('them','<span class="err">'+esc(d.message)+'</span>');}
        else if(ev[1]==='start'){loadTrace.id=d.trace_id;}
        else if(ev[1]==='file'){addFile(d);}
        else if(ev[1]==='action'){if(d.name==='open_application')openApp();else if(d.name==='open_fit')openFit();else if(d.name==='ask_consent')askConsent();}
        else if(ev[1]==='card'){addCard(d);}
      }
    }
    stepsEnd();clipsDone=true;
    if(!gotReply)wait.parentElement&&wait.parentElement.remove();
    if(loadTrace.id)loadTrace(loadTrace.id);loadBooks();
    if(replyBubble&&lastLang==='en')await speakEnglish(replyBubble);
    await drainClips();
  }catch(e){
    if(e.name!=='AbortError'){wait.parentElement&&wait.parentElement.remove();add('them','<span class="err">'+esc(String(e.message||e))+'</span>');}
  }
  if(state!=='listening')setState('idle');
  if($('conv').checked&&state==='idle')setTimeout(()=>{if(state==='idle')listen();},350);
}
function showReply(d){
  lastLang=d.language;
  const [body,tail]=(i=>i<0?[d.text,'']:[d.text.slice(0,i).trim(),d.text.slice(i)])(d.text.indexOf('(Sources:'));
  const el=add('them','',tail||/clause/i.test(d.text_en||'')?'cited':'');
  const words=body.split(/(\s+)/),step=Math.max(8,Math.min(60,1400/Math.max(1,words.length)));let k=0;
  const span=document.createElement('span');el.appendChild(span);
  const tick=()=>{k+=2;span.textContent=words.slice(0,k).join('');if(!hold)feed.scrollTop=feed.scrollHeight;
    if(k<words.length)setTimeout(tick,step*2);else{
      if(tail)el.insertAdjacentHTML('beforeend','<div class="src">'+esc(tail)+'</div>');
      if(d.language!=='en'&&d.text_en)el.insertAdjacentHTML('beforeend','<div class="en">English: '+esc(d.text_en.split('(Sources:')[0].trim())+'</div>');
      if(body.length>60){const q=curQ,bar=document.createElement('div');bar.className='save';
        bar.innerHTML='<button type="button" data-f="pdf">Save as PDF</button><button type="button" data-f="png">Save as image</button>';
        bar.querySelectorAll('button').forEach(b=>b.onclick=()=>exportAnswer(b.dataset.f,q,d));el.appendChild(bar);}
      followups(el.parentElement);
      if(!hold)feed.scrollTop=feed.scrollHeight;}};
  tick();el.dataset.body=body;return el;
}
function followups(afterMsg){
  col.querySelectorAll('.followups').forEach(x=>x.remove());
  const ideas=t('ideas').filter(q=>q!==curQ).slice(0,2);
  const wrap=document.createElement('div');wrap.className='followups';
  ideas.forEach(q=>{const b=document.createElement('button');b.className='idea';b.innerHTML='<i data-lucide="corner-down-right"></i><span>'+esc(q)+'</span>';b.onclick=()=>sendText(q);wrap.appendChild(b);});
  const c=document.createElement('button');c.className='idea';c.innerHTML='<i data-lucide="calendar-check"></i><span>'+esc(t('c3t'))+'</span>';c.onclick=()=>setRoute('close');wrap.appendChild(c);
  afterMsg.after(wrap);icons();
}

/* ---------- speaking ---------- */
function enqueue(b64){clipQ.push(b64);clipsDone=false;if(!player&&state!=='speaking')setState('speaking');pump();}
function pump(){
  if(player||!clipQ.length)return;
  player=new Audio('data:audio/wav;base64,'+clipQ.shift());
  player.onended=player.onerror=()=>{player=null;if(clipQ.length)pump();else if(clipsDone){if(state==='speaking')setState('idle');}};
  player.play().catch(()=>{player=null;});
}
function drainClips(){return new Promise(res=>{const w=()=>{if(!player&&!clipQ.length)res();else setTimeout(w,120);};w();});}
function stopSpeaking(){clipQ=[];clipsDone=true;if(player){player.onended=player.onerror=null;player.pause();player=null;}try{speechSynthesis.cancel();}catch{}}
function speakEnglish(el){return new Promise(res=>{try{const u=new SpeechSynthesisUtterance(el.dataset.body||'');u.lang='en-IN';setState('speaking');u.onend=u.onerror=()=>res();speechSynthesis.speak(u);}catch{res();}});}

/* ---------- microphone: record until you pause. English is turned into text by local Whisper. ---------- */
let mic=null,capturing=false,cancelCapture=null,finishCapture=null;
async function getMic(){
  if(mic&&mic.stream.active)return mic;
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  const ctx=new AudioContext(),an=ctx.createAnalyser();an.fftSize=1024;ctx.createMediaStreamSource(stream).connect(an);
  mic={stream,ctx,an,buf:new Float32Array(an.fftSize)};return mic;
}
const rms=m=>{m.an.getFloatTimeDomainData(m.buf);return Math.sqrt(m.buf.reduce((a,v)=>a+v*v,0)/m.buf.length);};
const setLvl=v=>document.documentElement.style.setProperty('--lvl',v);
function releaseMic(){if(mic){mic.stream.getTracks().forEach(x=>x.stop());mic.ctx.close();mic=null;}setLvl(0);cancelAnimationFrame(levelRAF);}
async function capture(){
  const m=await getMic();const rec=new MediaRecorder(m.stream),chunks=[];rec.ondataavailable=e=>chunks.push(e.data);
  return new Promise(res=>{
    let spoke=false,quiet=0,cancelled=false;const t0=Date.now();
    const loop=()=>{
      if(!capturing)return;
      const v=rms(m);setLvl(Math.min(1,v*9));const now=Date.now();
      if(v>0.02){spoke=true;quiet=0;}else if(spoke&&!quiet)quiet=now;
      if((spoke&&quiet&&now-quiet>1200)||now-t0>25000||(!spoke&&now-t0>8000)){rec.stop();return;}
      levelRAF=requestAnimationFrame(loop);
    };
    rec.onstop=()=>{capturing=false;setLvl(0);cancelCapture=finishCapture=null;res({blob:new Blob(chunks,{type:rec.mimeType||'audio/webm'}),spoke,cancelled});};
    cancelCapture=()=>{cancelled=true;rec.state!=='inactive'&&rec.stop();};
    finishCapture=()=>{rec.state!=='inactive'&&rec.stop();};
    capturing=true;rec.start();loop();
  });
}
async function sttText(blob,language){
  const fd=new FormData();fd.append('file',blob,'voice.webm');fd.append('language',language);
  try{const d=await (await fetch('/sim/stt',{method:'POST',body:fd,headers:H})).json();return d.text||'';}catch{return '';}
}
async function listen(){
  stopSpeaking();
  try{await getMic();}catch{setState('idle',esc(t('noMic')));return;}
  setState('listening');
  const r=await capture();
  if(!$('conv').checked)releaseMic();
  if(r.cancelled||state!=='listening')return;
  if(!r.spoke){setState('idle',esc(t('noHear')));return;}
  if(lang==='en'){
    setState('thinking','<span class="dots"><i></i><i></i><i></i></span> '+esc(t('transcribing')));
    const text=await sttText(r.blob,'en');
    if(!text){setState('idle',esc(t('noHear')));return;}
    add('me',esc(text));return turn({text});
  }
  const b=add('me','<audio controls src="'+URL.createObjectURL(r.blob)+'"></audio>');
  turn({blob:r.blob,userBubble:b});
}
let dictating=false;
async function dictate(){
  if(dictating){finishCapture&&finishCapture();return;}
  if(state!=='idle'){return;}
  try{await getMic();}catch{toast(t('noMic'),'err');return;}
  dictating=true;$('dictate').classList.add('rec');$('dictate').setAttribute('aria-pressed','true');status('<span class="dots"><i></i><i></i><i></i></span> '+esc(t('dictating')));
  const r=await capture();releaseMic();
  dictating=false;$('dictate').classList.remove('rec');$('dictate').setAttribute('aria-pressed','false');
  if(!r.spoke){status(esc(t('noHear')));return;}
  status('<span class="dots"><i></i><i></i><i></i></span> '+esc(t('transcribing')));
  const text=await sttText(r.blob,lang);
  status(esc(t('say')));
  if(!text){toast(t('noHear'),'err');return;}
  if($('reviewVoice').checked){msg.value=(msg.value?msg.value+' ':'')+text;grow();msg.focus();}
  else sendText(text);
}
$('dictate').onclick=dictate;
orb.onclick=()=>{
  if(state==='idle')return listen();
  if(cancelCapture)cancelCapture();
  stopSpeaking();if(ctl)ctl.abort();releaseMic();setState('idle');
};
$('reviewVoice').checked=localStorage.getItem('munim_review')!=='0';
$('reviewVoice').onchange=e=>localStorage.setItem('munim_review',e.target.checked?'1':'0');
/* barge-in: in conversation mode, speaking over the reply interrupts it */
setInterval(async()=>{
  if(!$('conv').checked||state!=='speaking')return;
  try{const m=await getMic();if(rms(m)>0.07){stopSpeaking();if(ctl)ctl.abort();setState('idle');listen();}}catch{}
},150);
$('conv').onchange=async e=>{if(e.target.checked){try{await getMic();}catch{e.target.checked=false;setState('idle',esc(t('noMic')));}}else releaseMic();};

/* ---------- text ---------- */
function sendText(x){x=(x||msg.value).trim();if(!x)return;msg.value='';grow();add('me',esc(x));turn({text:x});}
function grow(){msg.style.height='auto';msg.style.height=Math.min(120,msg.scrollHeight)+'px';$('send').disabled=!msg.value.trim();}
msg.addEventListener('input',grow);
msg.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendText();}});
$('send').onclick=()=>sendText();

/* ---------- files in chat ---------- */
$('attach').onclick=()=>$('file').click();
$('file').onchange=e=>{[...e.target.files].forEach(handleFile);e.target.value='';};
const size=n=>n>1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB';
async function handleFile(f){
  if(f.size>MAX_MB*1048576){add('them','<span class="err">'+esc(f.name)+' is over '+MAX_MB+' MB. Send a smaller file.</span>');return;}
  const pdf=f.type==='application/pdf'||/\.pdf$/i.test(f.name),aud=f.type.startsWith('audio/'),img=f.type.startsWith('image/');
  if(!pdf&&!aud&&!img){add('them','<span class="err">I can read PNG or JPEG photos, PDFs and audio files.</span>');return;}
  setRoute('chat');
  if(aud){const b=add('me','<audio controls src="'+URL.createObjectURL(f)+'"></audio>');return turn({blob:f,userBubble:b});}
  add('me',img?'<img src="'+URL.createObjectURL(f)+'" alt="Bill photo">':'<div class="filecard"><div class="ico"><i data-lucide="file-text"></i></div><div><b>'+esc(f.name)+'</b><small>PDF · '+size(f.size)+'</small></div></div>');
  const w=add('them','<span class="live"><span class="dots"><i></i><i></i><i></i></span> Reading your bill</span>');
  stepsReset();stepNow('ocr','Reading the bill');
  const fd=new FormData();fd.append('file',f,f.name);
  try{
    const d=await (await fetch('/sim/image',{method:'POST',body:fd,headers:H})).json();
    stepsEnd();w.parentElement.remove();add('them',esc(d.reply));if(d.trace_id)loadTrace(d.trace_id);loadBooks();loadDocs();loadReady();
  }catch(e){w.parentElement.remove();add('them','<span class="err">I could not upload that file. Check your connection and try again.</span>');}
}
const drop=$('drop');let depth=0;
addEventListener('dragenter',e=>{if(route!=='chat')return;e.preventDefault();depth++;drop.classList.add('on');});
addEventListener('dragleave',e=>{if(route!=='chat')return;e.preventDefault();if(--depth<=0){depth=0;drop.classList.remove('on');}});
addEventListener('dragover',e=>e.preventDefault());
addEventListener('drop',e=>{if(route!=='chat'){e.preventDefault();return;}e.preventDefault();depth=0;drop.classList.remove('on');[...e.dataTransfer.files].forEach(handleFile);});
addEventListener('paste',e=>{if(route!=='chat')return;[...(e.clipboardData?.files||[])].forEach(handleFile);});

/* ---------- side panel ---------- */
async function loadTrace(id){
  try{const d=await api('/sim/trace/'+id);
    $('trace').innerHTML=d.events.map(e=>'<div class="ev"><b>'+esc(e.event_type)+'</b> '+esc(e.tool_name||e.agent)+(e.payload&&e.payload.model_role?' · '+esc(e.payload.model_role):'')+(e.latency_ms?' · '+e.latency_ms+'ms':'')+'</div>').join('');}catch{}
}
async function loadBooks(){
  try{const d=await api('/sim/books',{headers:H});
    $('books').innerHTML=d.entries.length?d.entries.map(e=>'<div class="entry"><div>'+esc(e.category)+(e.review?'<span class="flag">check</span>':'')+'<small>'+esc(e.counterparty||'No name on bill')+' · '+esc(e.date)+(e.gst_pct?' · GST '+e.gst_pct+'%':'')+'</small></div><div class="amt '+e.direction+'">'+(e.direction==='in'?'+':'−')+money(e.amount)+'</div></div>').join('')
      :'<p class="empty">Nothing here yet. Send a bill to add it.</p>';}catch{}
}
async function loadStatus(){
  try{const s=await api('/sim/status');
    for(const [k,id] of [['boss','Boss'],['worker','Work'],['stt','Stt']]){$('d'+id).className='dot '+(s[k]?'ok':'bad');$('t'+id).textContent=s[k]?'ready':'offline';}}catch{}
}
/* ---------- plan, resources, memory ---------- */
const ACT={open_profile:['actProfile',()=>openFit()],
  upload_docs:['actDocs',()=>{$('side').classList.add('open');document.querySelector('#ptabs [data-p=files]').click();}],
  import_books:['actBooks',()=>setRoute('close')],review_findings:['actFix',()=>setRoute('close')],
  grant_consent:['actConsent',()=>askConsent()],build_file:['actBuild',()=>{document.querySelector('#ptabs [data-p=files]').click();$('bankBtn').click();}]};
const PLAN_ICON={done:'check-circle-2',needs_you:'circle-dot',pending:'circle'};
async function loadPlan(){
  try{const p=await api('/sim/goal',{headers:H});
    $('plan').innerHTML='<div class="score"><b>'+p.done+'</b><span>'+esc(t('planOf').replace('{n}',p.total))+'</span></div>'
      +'<div class="meter" role="img" aria-label="'+p.done+' / '+p.total+'"><i style="width:'+Math.round(100*p.done/p.total)+'%"></i></div>'
      +(p.note?'<p class="empty">'+esc(p.note)+'</p>':'')
      +p.steps.map(s=>'<div class="stp '+s.status+'"><span class="mk"><i data-lucide="'+PLAN_ICON[s.status]+'"></i></span><div><b>'+esc(s.title)+'</b><small>'+esc(s.detail)+'</small>'
        +((s.status==='needs_you'||s.action==='build_file')&&ACT[s.action]?'<button class="ghost sm" data-act="'+s.action+'">'+esc(t(ACT[s.action][0]))+'</button>':'')+'</div></div>').join('');
    $('plan').querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>ACT[b.dataset.act][1]());
    icons();}catch{$('plan').innerHTML='<p class="empty">'+esc(t('oops'))+'</p>';}
}
function resBar(label,used,cap){const pct=cap?Math.min(100,Math.round(100*used/cap)):0;
  return '<div class="res"><div><span>'+esc(label)+'</span><b>'+(used/1024).toFixed(1)+' / '+(cap/1024).toFixed(0)+' GB</b></div><div class="meter" role="img" aria-label="'+esc(label)+' '+pct+'%"><i style="width:'+pct+'%"></i></div></div>';}
async function loadSystem(){
  try{const s=await api('/sim/status');const r=s.resources||{};
    $('res').innerHTML=r.vram_cap_mib?resBar(t('vram'),r.vram_used_mib,r.vram_cap_mib)+resBar(t('ram'),r.ram_models_mib,r.ram_models_cap_mib)+'<p class="empty">'+esc(t('resNote'))+'</p>'
      :'<p class="empty">'+esc(t('resNone'))+'</p>';}catch{}
  try{const m=await api('/sim/memory',{headers:H});const p=m.profile||{};const ints=Object.keys(p.interests||{});
    const facts=[p.sector&&'Business: '+p.sector,p.state&&'State: '+p.state,p.employees&&'Staff: '+p.employees,
      p.loan_amount_asked_rupees&&'Loan asked: '+money(p.loan_amount_asked_rupees),ints.length&&'Interested in: '+ints.join(', ')].filter(Boolean);
    $('mem').innerHTML=(facts.length||m.recent.length)
      ?'<ul class="memlist">'+facts.map(f=>'<li>'+esc(f)+'</li>').join('')+'</ul>'
        +(m.recent.length?'<p class="empty">'+esc(t('memRecent'))+': '+m.recent.slice(-3).map(r=>esc(r.q)).join(' · ')+'</p>':'')
        +'<button class="ghost sm" id="memForget">'+esc(t('memForget'))+'</button>'
      :'<p class="empty">'+esc(t('memNone'))+'</p>';
    const f=$('memForget');
    if(f)f.onclick=async()=>{if(await confirmBox(t('memForgetT'),t('memForgetD'),t('memForget'))){await api('/sim/memory',{method:'DELETE',headers:H});toast(t('memCleared'));loadSystem();}};}catch{}
}
let curQ2='';
function addFile(f){add('them','<a class="chip" href="'+esc(f.url)+'" download="'+esc(f.name)+'"><i data-lucide="download"></i>'+esc(f.name)+'</a>'
  +(f.verify?' <a class="chip" href="'+esc(f.verify)+'" target="_blank" rel="noopener"><i data-lucide="shield-check"></i>Verify page</a>':''));}
async function exportAnswer(fmt,q,d){
  try{const r=await post('/sim/export',{fmt,question:q,reply:d.text,reply_en:d.text_en||'',language:d.language});addFile(r);}
  catch{add('them','<span class="err">I could not create that file. Please try again.</span>');}
}
const KIND={invoice:'Bill',udyam_certificate:'Udyam certificate',gst_certificate:'GST certificate',id_proof:'ID proof',bank_statement:'Bank statement',other:'Other'};
async function loadDocs(){
  try{const d=await api('/sim/documents',{headers:H});
    const sel=(id,arr)=>{const s=$(id);if(!s.options.length)s.innerHTML=arr.map(x=>'<option>'+esc(x)+'</option>').join('');};sel('aBank',d.banks);sel('aScheme',d.schemes);
    $('docs').innerHTML=d.documents.length?d.documents.map(x=>'<label class="doc"><input type="checkbox" data-id="'+x.id+'"'+(x.include?' checked':'')+'><span>'+esc(x.filename)
      +'<small>'+esc(KIND[x.kind]||x.kind)+(x.summary?' · '+esc(x.summary):'')+'</small></span></label>').join('')
      :'<p class="empty">Upload a certificate, ID or bank statement and it appears here.</p>';
    $('docs').querySelectorAll('input').forEach(c=>c.onchange=()=>fetch('/sim/documents/'+c.dataset.id+'/include',{method:'POST',headers:JH,body:JSON.stringify({include:c.checked})}));
  }catch{}
}
$('bankBtn').onclick=async()=>{
  const b=$('bankBtn');b.disabled=true;b.textContent='Preparing…';setRoute('chat');
  try{const r=await post('/sim/dossier');addFile(r);}catch{add('them','<span class="err">I could not build the bank file. Please try again.</span>');}
  b.disabled=false;b.textContent='Download bank file (PDF)';
};
function openApp(){$('aErr').textContent='';openDlg($('appDlg'),$('aAmt'));}
$('appBtn').onclick=openApp;$('aCancel').onclick=()=>closeDlg($('appDlg'));
$('appForm').onsubmit=async e=>{
  e.preventDefault();const go=$('aGo');go.disabled=true;go.textContent='Drafting…';$('aErr').textContent='';
  try{const r=await post('/sim/application',{bank:$('aBank').value,scheme:$('aScheme').value,amount:$('aAmt').value,purpose:$('aPur').value,tenure:$('aTen').value,phone:$('aPhone').value,address:$('aAddr').value,language:lang});
    if(r.error){$('aErr').textContent=r.error;}else{closeDlg($('appDlg'));setRoute('chat');add('them','Your loan application draft is ready. Review it, fill the blanks and sign it. Nothing has been submitted.');addFile(r);}
  }catch{$('aErr').textContent=t('oops');}
  go.disabled=false;go.textContent='Draft it';
};

/* ---------- readiness, consent, scheme fit ---------- */
const STATE={eligible:'Meets the conditions checked',almost:'Need a few more facts',not_eligible:'Not eligible',unverified:'Not confirmed'};
const MARK={pass:'Met',fail:'Not met',unknown:'Not known yet',todo:'To do'};
function readyHTML(d){
  const a=d.affordability;
  return '<div class="score"><b>'+d.score+'</b><span>out of 100 · '+esc({ready:'ready for a lender',getting_there:'getting there',early:'still early'}[d.band])+'</span></div>'
   +'<div class="meter" role="img" aria-label="Score '+d.score+' of 100"><i style="width:'+d.score+'%"></i></div>'
   +(a?'<p class="empty">Affordability: '+esc(a.band)+' ('+a.score+'/100). Cautious instalment up to '+money(a.emi)+' a month.</p>':'')
   +d.factors.map(f=>'<div class="fac"><div>'+esc(f.label)+'<small>'+esc(f.reason)+'</small>'+(f.gain?'<small>'+esc(f.action)+'</small>':'')+'</div><div>'
     +(f.gain?'<span class="gain">+'+f.gain+'</span>':'<b>'+f.points+'/'+f.max+'</b>')+'</div></div>').join('')
   +(d.gst_issues?'<p class="empty" style="margin-top:8px">'+d.gst_issues+(d.gst_issues===1?' entry also holds':' entries also hold')+' up your GST draft. Fixing '+(d.gst_issues===1?'it':'them')+' helps both.</p>':'')
   +'<p class="empty" style="margin-top:8px">'+esc(d.limitation)+'</p>';
}
async function loadReady(){
  try{const c=await api('/sim/consent',{headers:H});$('consent').checked=c.on;
    if(!c.on){$('ready').innerHTML='<p class="empty">Turn on the switch below to see how ready your books look to a lender.</p>';return;}
    const r=await api('/sim/readiness',{headers:H});
    $('ready').innerHTML=r.data?readyHTML(r.data):'<p class="empty">'+esc(r.text)+'</p>';}catch{}
}
$('consent').onchange=async e=>{await post('/sim/consent',{on:e.target.checked});loadReady();};
$('readyBtn').onclick=loadReady;
function askConsent(){$('side').classList.add('open');document.querySelector('#ptabs [data-p=ready]').click();const r=$('consentRow');r.classList.remove('flash');void r.offsetWidth;r.classList.add('flash');r.scrollIntoView({block:'center'});}
function fitHTML(list){
  return list.map(f=>'<details class="sc"'+(f.status==='eligible'||f.status==='not_eligible'?' open':'')+'><summary>'+esc(f.name)+'<span class="pill '+f.status+'">'+esc(STATE[f.status])+'</span></summary>'
    +(f.status==='unverified'?'<div class="cr">'+esc(f.summary)+'</div>':'')
    +f.criteria.map(c=>'<div class="cr"><b class="'+c.status+'">'+MARK[c.status]+'</b> · '+esc(c.label)+'<small>'+esc(c.why)+'</small>'
      +(c.status==='fail'||c.status==='todo'?'<small><b>What would change this:</b> '+esc(c.need)+'</small>':'')
      +(c.clause_id?'<small>Official clause: '+(c.source_url?'<a href="'+esc(c.source_url)+'" target="_blank" rel="noopener">'+esc(c.clause_ref)+'</a>':esc(c.clause_ref))+'</small>':'')+'</div>').join('')+'</details>').join('')
    +'<p class="empty">This checks the published conditions only. The bank or portal decides the application.</p>';
}
function addCard(d){
  let b;
  if(d.kind==='fit')b=add('them',fitHTML(d.data),'cardwrap');
  else if(d.kind==='readiness'){b=add('them',readyHTML(d.data),'cardwrap');loadReady();}
  const prev=b&&b.parentElement.previousElementSibling;
  if(prev){hold=true;requestAnimationFrame(()=>{feed.style.scrollBehavior='auto';prev.scrollIntoView({block:'start'});feed.style.scrollBehavior='';});}
}
let fitLoaded=false;
async function openFit(){
  openDlg($('fitDlg'));
  if(fitLoaded)return;
  try{const d=await api('/sim/fit',{headers:H});
    $('fitFields').innerHTML=d.fields.map(f=>{const v=d.attrs[f.key];const id='f_'+f.key;let c;
      if(f.type==='choice')c='<select id="'+id+'" data-k="'+f.key+'"><option value="">Not sure</option>'+f.options.map(o=>'<option value="'+esc(o.value)+'"'+(v===o.value?' selected':'')+'>'+esc(o.label)+'</option>').join('')+'</select>';
      else if(f.type==='bool')c='<select id="'+id+'" data-k="'+f.key+'"><option value="">Not sure</option><option value="true"'+(v===true?' selected':'')+'>Yes</option><option value="false"'+(v===false?' selected':'')+'>No</option></select>';
      else c='<input id="'+id+'" data-k="'+f.key+'" inputmode="decimal" value="'+(v!=null?esc(String(v)):'')+'">';
      return '<div><label for="'+id+'">'+esc(f.label)+'</label>'+c+'</div>';}).join('');
    fitLoaded=true;if(d.results.length)$('fitOut').innerHTML=fitHTML(d.results);
  }catch{$('fitOut').innerHTML='<p class="err">I could not load the questions. Please try again.</p>';}
}
$('fitBtn').onclick=openFit;$('fitClose').onclick=()=>closeDlg($('fitDlg'));
$('fitForm').onsubmit=async e=>{e.preventDefault();const go=$('fitGo');go.disabled=true;go.textContent='Checking…';
  const attrs={};$('fitFields').querySelectorAll('[data-k]').forEach(el=>{if(el.value!=='')attrs[el.dataset.k]=el.value;});
  try{const r=await post('/sim/fit',{attrs});$('fitOut').innerHTML=fitHTML(r.results);$('fitOut').scrollIntoView({behavior:'smooth',block:'start'});}
  catch{$('fitOut').innerHTML='<p class="err">'+esc(t('oops'))+'</p>';}
  go.disabled=false;go.textContent='Check my fit';};

/* ---------- business profile ---------- */
async function loadProfile(){
  try{const p=await api('/sim/profile',{headers:H});$('bizName').textContent=p.name;
    $('bName').value=p.is_new?'':p.name;$('bGst').value=p.gstin||'';if(p.is_new&&!localStorage.getItem('munim_skip'))openDlg($('setup'));}catch{}
}
$('bizBtn').onclick=()=>{openDlg($('setup'),$('bName'));};
$('setupSkip').onclick=()=>{localStorage.setItem('munim_skip','1');closeDlg($('setup'));};
$('setupForm').onsubmit=async e=>{e.preventDefault();
  const r=await post('/sim/profile',{name:$('bName').value,gstin:$('bGst').value});
  if(r.name){$('bizName').textContent=r.name;closeDlg($('setup'));}};

/* ======================================================================
   CLOSE THE MONTH
   ====================================================================== */
const prevMonth=()=>{const d=new Date();d.setDate(1);d.setMonth(d.getMonth()-1);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');};
const CL={month:prevMonth(),data:null,imports:[],busy:false,code:null,loaded:false,err:''};
async function loadClose(){
  if(CL.loaded){renderClose();return;}
  renderClose();
  try{const d=await api('/sim/close/last',{headers:H});CL.loaded=true;if(d.task){CL.data=d;CL.month=d.task.period_start.slice(0,7);}else CL.autonomy=d.autonomy;}
  catch{CL.err=t('oops');}
  renderClose();
}
function clStep(){
  const d=CL.data;if(CL.busy)return 2;if(!d||!d.task)return 1;
  if(d.receipt)return 6;if(d.approval_id)return 5;
  const crit=d.findings.filter(f=>f.severity==='critical'&&f.status==='open').length;
  return crit?3:4;
}
function renderClose(){
  const root=$('closeRoot');if(!root)return;
  const d=CL.data,cur=clStep(),crit=d?d.findings.filter(f=>f.severity==='critical'&&f.status==='open').length:0;
  const on=(d&&d.autonomy!==undefined)?d.autonomy:(CL.autonomy!==false);
  const labels=[t('st1'),t('st2'),t('st3'),t('st4'),t('st5')];
  root.innerHTML=`
  <div class="hero"><h1>${esc(t('closeH'))}</h1><p>${esc(t('closeSub'))}</p></div>
  <div class="card"><ol class="stepper" aria-label="Progress">${labels.map((l,i)=>`<li class="${i+1<cur?'done':i+1===cur?'now':''}"${i+1===cur?' aria-current="step"':''}>${esc(l)}</li>`).join('')}</ol></div>
  ${CL.err?`<div class="banner warn"><i data-lucide="circle-alert"></i><span>${esc(CL.err)}</span></div>`:''}
  ${(d&&d.task&&!CL.showImport)?`<div class="card"><div class="compact"><span style="width:38px;height:38px;border-radius:12px;background:var(--teal-soft);color:var(--teal-d);display:grid;place-items:center"><i data-lucide="database"></i></span>
     <div class="grow"><b>${esc(t('impH'))}</b><div class="muted">${esc(t('month'))}: ${esc(CL.month)}${CL.imports.length?' · '+CL.imports.length+' file(s) this session':''}</div></div>
     <button class="btn ghost sm" id="clMore"><i data-lucide="plus"></i>${esc(t('choose'))}</button>
     <button class="btn primary sm" id="clRun" ${CL.busy?'disabled':''}><i data-lucide="${CL.busy?'loader-circle':'refresh-cw'}"></i>${esc(t('recheck'))}</button></div></div>`
  :`<div class="card" id="impCard">
    <div class="card-h"><span class="ico"><i data-lucide="upload"></i></span><div class="grow"><h2>${esc(t('impH'))}</h2><small>${esc(t('month'))}: <input type="month" id="clMonth" class="field" style="width:auto;padding:6px 10px" value="${esc(CL.month)}" aria-label="${esc(t('month'))}"></small></div></div>
    <div class="dz" id="dz"><div class="ic"><i data-lucide="file-up"></i></div><p>${esc(t('impD'))}</p>
      <div class="acts" style="justify-content:center"><button class="btn primary" id="clPick"><i data-lucide="folder-open"></i>${esc(t('choose'))}</button>
      <a class="btn ghost" href="/sim/template.csv" download><i data-lucide="download"></i>${esc(t('tpl'))}</a></div></div>
    <input type="file" id="clFile" accept=".csv,.xml,.txt,text/csv,text/xml" multiple hidden>
    <div id="impList">${CL.imports.map(i=>`<div class="fileline"><i data-lucide="${i.ok?'circle-check':'circle-alert'}"></i><span>${esc(i.name)} · ${esc(i.text)}</span></div>`).join('')}</div>
    <div class="acts" style="margin-top:16px"><button class="btn primary" id="clRun" ${CL.busy?'disabled':''}><i data-lucide="${CL.busy?'loader-circle':'shield-check'}"></i>${esc(d&&d.task?t('recheck'):t('runBtn'))}</button></div>
  </div>`}
  ${CL.busy?`<div class="card progress" aria-live="polite"><div class="card-h"><span class="ico"><i data-lucide="loader-circle" style="animation:spin 1.2s linear infinite"></i></span><div class="grow"><h2>${esc(t('running'))}</h2></div></div>
     <ol class="steps"><li id="rp1" class="now"><span class="tick"></span>${esc(t('rs1'))}</li><li id="rp2"><span class="tick"></span>${esc(t('rs2'))}</li><li id="rp3"><span class="tick"></span>${esc(t('rs3'))}</li></ol></div>`:''}
  ${d&&d.task&&!CL.busy?closeResult(d,crit):''}
  <div class="card"><div class="card-h"><span class="ico"><i data-lucide="power"></i></span><div class="grow"><h2>${esc(t('killT'))}</h2><small id="killTxt">${esc(on?t('killOn'):t('killOff'))}</small></div>
    <label class="switch"><input type="checkbox" id="killSw" ${on?'checked':''} aria-label="${esc(t('killT'))}"></label></div>
    <div class="banner"><i data-lucide="info"></i><span>${esc(t('caNote'))}</span></div></div>`;
  icons();bindClose();
}
function sevName(s){return {critical:t('sevC'),warn:t('sevW'),info:t('sevI')}[s];}
function closeResult(d,crit){
  const r=d.snapshot?d.snapshot.return.figures:null;
  const tiles=r?`<div class="card"><div class="card-h"><span class="ico"><i data-lucide="file-spreadsheet"></i></span><div class="grow"><h2>${esc(t('draftH'))}</h2><small>${esc(t('draftNote'))}</small></div></div>
    <div class="grid4"><div class="tile"><span class="lbl">${esc(t('outTax'))}</span><span class="val">${rupees(r.output_tax_paise)}</span></div>
    <div class="tile"><span class="lbl">${esc(t('inCredit'))}</span><span class="val">${rupees(r.input_credit_paise)}</span></div>
    <div class="tile net"><span class="lbl">${esc(t('netPay'))}</span><span class="val">${rupees(r.net_payable_paise)}</span></div>
    <div class="tile"><span class="lbl">${esc(t('carry'))}</span><span class="val">${rupees(r.credit_carry_forward_paise)}</span></div></div></div>`:'';
  const fs=d.findings.filter(f=>f.status==='open');
  const findings=`<div class="card"><div class="card-h"><span class="ico"><i data-lucide="list-checks"></i></span><div class="grow"><h2>${esc(t('fH'))}</h2></div>
     ${['critical','warn','info'].map(s=>{const n=fs.filter(f=>f.severity===s).length;return n?`<span class="chip ${s==='critical'?'crit':s==='warn'?'warn':'info'}">${n} ${esc(sevName(s))}</span>`:'';}).join('')}</div>
     ${fs.length?fs.map(findingHTML(d)).join(''):`<div class="banner" style="background:var(--ok-soft);color:var(--ok)"><i data-lucide="circle-check"></i><span>${esc(t('fNone'))}</span></div>`}</div>`;
  return tiles+findings+approvalCard(d,crit)+(d.receipt?receiptCard(d.receipt):'');
}
const findingHTML=d=>f=>{
  const cls=f.severity==='critical'?'crit':f.severity;
  const ents=(f.entry_ids||[]).map(id=>d.entries[id]).filter(Boolean);
  return `<div class="finding ${cls}"><div class="body"><span class="chip ${cls==='crit'?'crit':cls}">${esc(sevName(f.severity))}</span>
    <p>${esc(f.message)}</p>
    ${f.rule_ref?`<details><summary>${esc(t('why'))}</summary><p class="muted">${esc(f.rule_ref)}</p></details>`:''}
    ${ents.length?`<div class="ents">${ents.map(e=>`<div class="ent"><span class="d"><b>${money(e.amount)}</b> · ${esc(e.party||'—')} · ${esc(e.date)}${e.invoice_no?' · '+esc(e.invoice_no):''}${e.review?' <span class="flag">check</span>':''}</span>
       ${e.review?`<button class="btn ghost sm" data-ok="${e.id}"><i data-lucide="check"></i>${esc(t('confirmBtn'))}</button>`:''}
       <button class="btn danger sm" data-rm="${e.id}"><i data-lucide="trash-2"></i>${esc(t('removeBtn'))}</button></div>`).join('')}</div>`:''}</div></div>`;
};
function approvalCard(d,crit){
  if(d.receipt)return '';
  const blocked=crit>0;
  const body=d.approval_id?
    `<div class="banner" style="background:var(--ok-soft);color:var(--ok)"><i data-lucide="circle-check"></i><span>${esc(t('apDone'))}</span></div>
     <div class="acts"><button class="btn primary" id="clFile"><i data-lucide="send"></i>${esc(t('filedBtn'))}</button></div>`
   :blocked?`<div class="banner warn"><i data-lucide="lock"></i><span>${esc(t('apBlocked'))} (${crit}).</span></div>`
   :(CL.code?`<p>${esc(t('codeIs'))}</p><div class="codebox num" id="theCode">${esc(CL.code)}</div>
      <label for="clCode" style="display:block;margin:14px 0 6px;font-weight:500">${esc(t('codeLbl'))}</label>
      <div class="kv"><input id="clCode" class="field" style="max-width:200px" inputmode="numeric" maxlength="6" autocomplete="one-time-code"><button class="btn primary" id="clApprove"><i data-lucide="badge-check"></i>${esc(t('apGo'))}</button></div>
      <div class="hint err" id="clCodeErr" role="alert"></div>`
      :`<div class="acts"><button class="btn primary" id="clGetCode"><i data-lucide="key-round"></i>${esc(t('getCode'))}</button></div>`);
  return `<div class="card"><div class="card-h"><span class="ico"><i data-lucide="badge-check"></i></span><div class="grow"><h2>${esc(t('apH'))}</h2><small>${esc(t('apD'))}</small></div></div>${body}</div>`;
}
function receiptCard(r){
  return `<div class="receipt"><span class="stamp">${esc(t('sim'))}</span><div class="card-h"><span class="ico"><i data-lucide="receipt"></i></span><div class="grow"><h2>${esc(t('rcH'))}</h2><small>${esc(t('rcN'))}</small></div></div>
    <div class="kv"><span class="muted">${esc(t('ref'))}</span><code id="rcRef">${esc(r.reference)}</code><button class="btn ghost sm" id="rcCopy"><i data-lucide="copy"></i>${esc(t('copy'))}</button></div>
    <p class="muted" style="margin:12px 0 0">${esc(r.period||'')} · ${esc(t('netPay'))}: ${rupees(r.net_payable_paise)}</p></div>`;
}
function bindClose(){
  const more=$('clMore');if(more)more.onclick=()=>{CL.showImport=true;renderClose();};
  const run0=$('clRun');if(run0)run0.onclick=()=>runClose(false);
  if($('clPick')){
    $('clPick').onclick=()=>$('clFile').click();
    $('clFile').onchange=e=>{importFiles([...e.target.files]);e.target.value='';};
    const dz=$('dz');
    ['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('over');}));
    ['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('over');}));
    dz.addEventListener('drop',e=>importFiles([...e.dataTransfer.files]));
    $('clMonth').onchange=e=>{CL.month=e.target.value||CL.month;};
  }
  $('killSw').onchange=async e=>{try{const r=await post('/sim/autonomy',{enabled:e.target.checked});if(CL.data)CL.data.autonomy=r.enabled;CL.autonomy=r.enabled;$('killTxt').textContent=r.enabled?t('killOn'):t('killOff');}catch{toast(t('oops'),'err');}};
  document.querySelectorAll('[data-rm]').forEach(b=>b.onclick=async()=>{
    if(!await confirmBox(t('rmT'),t('rmD'),t('rmGo')))return;
    try{await api('/sim/entries/'+b.dataset.rm,{method:'DELETE',headers:H});toast(t('entryGone'));await runClose(true);}catch{toast(t('oops'),'err');}});
  document.querySelectorAll('[data-ok]').forEach(b=>b.onclick=async()=>{
    try{await api('/sim/entries/'+b.dataset.ok+'/confirm',{method:'POST',headers:H});toast(t('entryOk'));await runClose(true);}catch{toast(t('oops'),'err');}});
  const gc=$('clGetCode');if(gc)gc.onclick=async()=>{
    try{const r=await post('/sim/code',{snapshot_id:CL.data.snapshot.id});if(r.error){toast(r.error,'err');return;}CL.code=r.code;renderClose();$('clCode')&&$('clCode').focus();}catch{toast(t('oops'),'err');}};
  const ap=$('clApprove');if(ap)ap.onclick=async()=>{
    try{const r=await post('/sim/approve',{snapshot_id:CL.data.snapshot.id,code:$('clCode').value});
      if(r.error){$('clCodeErr').textContent=r.error;return;}CL.data.approval_id=r.approval_id;CL.code=null;renderClose();toast(t('apDone'));
      const nx=$('clFile');if(nx){nx.scrollIntoView({block:'center',behavior:'smooth'});nx.focus({preventScroll:true});}}catch{toast(t('oops'),'err');}};
  const fl=$('clFile');if(fl)fl.onclick=async()=>{
    fl.disabled=true;try{const r=await post('/sim/file',{approval_id:CL.data.approval_id});
      if(r.error){toast(r.error,'err');if(r.stale){CL.data.approval_id=null;await runClose(true);}else fl.disabled=false;return;}CL.data.receipt=r.receipt;renderClose();$('rcRef')&&$('rcRef').scrollIntoView({block:'center'});}catch{toast(t('oops'),'err');fl.disabled=false;}};
  const cp=$('rcCopy');if(cp)cp.onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText($('rcRef').textContent).then(()=>toast(t('copied')));};
}
async function importFiles(files){
  for(const f of files){
    if(f.size>5*1048576){CL.imports.push({name:f.name,ok:false,text:'over 5 MB'});continue;}
    const text=await f.text();const head=text.trimStart();
    const kind=head.startsWith('<')?'tally':/supplier_gstin/i.test(head.split('\n')[0])?'gstr2b':'csv';
    try{
      const r=await post('/sim/import',{kind,text});
      if(r.error){CL.imports.push({name:f.name,ok:false,text:r.error});continue;}
      const parts=kind==='gstr2b'?[(r.gstr2b_lines||0)+' supplier lines']:[(r.added||0)+' '+t('imported'),r.skipped_duplicates?r.skipped_duplicates+' '+t('skippedDup'):'',r.flagged_for_review?r.flagged_for_review+' '+t('flagged'):'',(r.rows_rejected&&r.rows_rejected.length)?r.rows_rejected.length+' '+t('rejected'):''].filter(Boolean);
      CL.imports.push({name:f.name+' ('+({tally:'Tally',csv:'CSV',gstr2b:'GSTR-2B'}[kind])+')',ok:true,text:parts.join(' · ')});
    }catch{CL.imports.push({name:f.name,ok:false,text:t('oops')});}
  }
  CL.showImport=true;renderClose();
}
async function runClose(quiet){
  CL.busy=true;CL.err='';CL.code=null;renderClose();
  const timers=[setTimeout(()=>{$('rp1')&&($('rp1').className='done');$('rp2')&&($('rp2').className='now');},1200),setTimeout(()=>{$('rp2')&&($('rp2').className='done');$('rp3')&&($('rp3').className='now');},2600)];
  try{const d=await post('/sim/close',{month:CL.month,analyse:false});CL.data=d;CL.loaded=true;}
  catch{CL.err=t('oops');}
  timers.forEach(clearTimeout);CL.busy=false;CL.showImport=false;renderClose();
  if(!quiet&&CL.data){const el=document.querySelector('.finding,.tile');el&&el.scrollIntoView({behavior:'smooth',block:'start'});}
}

/* ======================================================================
   INSIGHTS
   ====================================================================== */
const INS={data:null,series:null,busy:false,loaded:false,err:''};
async function loadInsights(){
  renderInsights();
  try{[INS.data,INS.series]=await Promise.all([api('/sim/insights',{headers:H}),api('/sim/series?months=12',{headers:H})]);INS.loaded=true;INS.err='';}
  catch{INS.err=t('oops');}
  renderInsights();
}
function spark(vals){
  const v=(vals||[]).map(x=>x==null||!isFinite(x)?null:x);const pts=v.map((y,i)=>[i,y]).filter(p=>p[1]!=null);
  if(pts.length<2)return '';
  const W=120,Hh=40,xs=i=>4+(W-8)*i/Math.max(1,v.length-1),ys=[...pts.map(p=>p[1])],mn=Math.min(...ys),mx=Math.max(...ys),span=(mx-mn)||1;
  const y=val=>Hh-5-(Hh-12)*(val-mn)/span;
  const d=pts.map((p,k)=>(k?'L':'M')+xs(p[0]).toFixed(1)+' '+y(p[1]).toFixed(1)).join(' ');
  const last=pts[pts.length-1];
  return `<svg class="spark" viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none" role="img" aria-label="Trend over ${pts.length} months"><path class="a" d="${d} L${xs(last[0]).toFixed(1)} ${Hh} L${xs(pts[0][0]).toFixed(1)} ${Hh} Z"/><path class="l" d="${d}"/><circle cx="${xs(last[0]).toFixed(1)}" cy="${y(last[1]).toFixed(1)}" r="3.5"/></svg>`;
}
const fmtVal=(v,u)=>u==='ratio'?(v*100).toFixed(1)+'%':(u&&u.startsWith('rupees'))?money(v)+(u.includes('item')?' per item':''):(Math.round(v*100)/100).toLocaleString('en-IN');
const chipFor=f=>f.status==='validated'?`<span class="chip ok"><i data-lucide="badge-check"></i>${esc(t('chV'))}</span>`:f.status==='indicative'?`<span class="chip warn">${esc(t('chI'))}</span>`:`<span class="chip info">${esc(t('chB'))}</span>`;
function renderInsights(){
  const root=$('insRoot');if(!root)return;
  const ins=INS.data&&INS.data.insights&&INS.data.insights[0];
  const facts=ins?ins.facts:[];const own=facts.filter(f=>!f.market),mk=facts.filter(f=>f.market);
  const S=INS.series;
  const hero=`<div class="hero"><h1>${esc(t('insH'))}</h1><p>${esc(t('insSub'))}</p><div class="row">
    <button class="btn primary" id="insRefresh" ${INS.busy?'disabled':''}><i data-lucide="${INS.busy?'loader-circle':'refresh-cw'}"></i>${esc(t('refresh'))}</button>
    ${ins?`<span style="opacity:.9">${esc(t('updated'))} ${esc(new Date(ins.at.replace(' ','T')).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}))}</span>`:''}
    ${INS.busy?`<span style="opacity:.9">~1 min</span>`:''}</div></div>`;
  if(!INS.loaded&&!INS.err){root.innerHTML=hero+`<div class="grid4">${'<div class="skeleton" style="height:130px"></div>'.repeat(4)}</div><div class="skeleton" style="height:220px"></div>`;icons();bindIns();return;}
  if(INS.err){root.innerHTML=hero+`<div class="banner warn"><i data-lucide="circle-alert"></i><span>${esc(INS.err)}</span></div>`;icons();bindIns();return;}
  if(!ins){root.innerHTML=hero+`<div class="card"><div class="empty-state">${emptySvg()}<h2 style="font:700 20px var(--font-d);margin:0">${esc(t('noIns'))}</h2>
     <div class="acts"><button class="btn primary" id="goClose"><i data-lucide="calendar-check"></i>${esc(t('nClose'))}</button><button class="btn ghost" id="goChat"><i data-lucide="receipt-text"></i>${esc(t('c2t'))}</button></div></div></div>`;
    icons();bindIns();return;}
  const byName=n=>own.find(f=>f.name===n);
  const share=S?S.purchases.map((p,i)=>S.sales[i]>0?100*p/S.sales[i]:null):null;
  const growth=S?S.sales.map((s,i)=>i&&S.sales[i-1]>0?100*(s-S.sales[i-1])/S.sales[i-1]:null):null;
  const tiles=[
    {n:'Gross margin',l:t('mMargin'),sp:S&&S.margin_pct},
    {n:'Purchases as a share of sales',l:t('mBuy'),sp:share},
    {n:'Monthly sales growth',l:t('mGrow'),sp:growth},
    {n:'Input tax credit as a share of tax charged',l:t('mItc'),sp:null}].map(m=>{const f=byName(m.n);if(!f)return '';
      return `<div class="tile metric"><span class="lbl">${esc(m.l)}</span><span class="val">${fmtVal(f.value,f.unit)}</span>${m.sp?spark(m.sp):''}<div class="foot">${chipFor(f)}</div></div>`;}).join('');
  const found=own.map(f=>{
    const ev=(INS.data.formulas||[]).find(x=>x.expression===f.expression);const e=ev?ev.evidence:{};
    const how=f.kind==='predictive'&&f.improvement!=null
      ?`${(100*f.improvement).toFixed(0)}% ${esc(t('beat'))} · ${e.n_months||''} ${esc(t('months'))}`
      :`${esc(f.expression)} · ${e.n_months||''} ${esc(t('months'))}`;
    return `<div class="fact"><div class="t"><b>${esc(f.name)}</b>${chipFor(f)}<details><summary>${esc(t('how'))}</summary><p class="muted" style="margin:6px 0 0">${how}</p>${f.why?`<p class="muted" style="margin:6px 0 0">${esc(f.why)}</p>`:''}${e.reason?`<p class="muted" style="margin:6px 0 0">${esc(e.reason)}</p>`:''}</details></div><span class="v">${fmtVal(f.value,f.unit)}</span></div>`;}).join('');
  const you=(byName('Gross margin')||{}).value;const youPct=you!=null?you*100:null;
  const market=mk.length?`<div class="card"><div class="card-h"><span class="ico"><i data-lucide="globe"></i></span><div class="grow"><h2>${esc(t('mkH'))}</h2></div></div>
    ${mk.map(m=>{const lo=m.low,hi=m.high==null?m.low:m.high;const isM=/margin/i.test(m.market)&&youPct!=null;
      const maxv=Math.max(hi,isM?youPct:0)*1.25||1;const pct=x=>(100*x/maxv).toFixed(1)+'%';
      let host='';try{host=new URL(m.source).hostname.replace(/^www\./,'');}catch{}
      return `<div class="fact"><div class="t"><b>${esc(m.market)}</b> <span class="chip ${m.official?'ok':'warn'}">${esc(m.official?t('off'):t('notOff'))}</span>
        <small>${esc(t('webR'))}: ${lo}${m.high!=null?'–'+hi:''}${esc(m.unit||'')} · <a href="${esc(m.source)}" target="_blank" rel="noopener">${esc(host)}</a></small>
        ${isM?`<div class="range" role="img" aria-label="${esc(t('yourM'))} ${youPct.toFixed(1)}%, ${esc(t('webR'))} ${lo} to ${hi}"><div class="track"></div><div class="band" style="left:${pct(lo)};width:calc(${pct(hi)} - ${pct(lo)} + 4px)"></div><div class="you" style="left:${pct(youPct)}"></div><span class="tag" style="left:${pct(youPct)}">${esc(t('yourM'))} ${youPct.toFixed(1)}%</span><div class="ticks"><span>0</span><span>${maxv.toFixed(0)}%</span></div></div>`:''}</div></div>`;}).join('')}</div>`:'';
  const notes=(ins.notes||[]).length?`<div class="card"><div class="card-h"><span class="ico"><i data-lucide="book-open"></i></span><div class="grow"><h2>${esc(t('notesH'))}</h2><small>${esc(t('notesS'))}</small></div></div>
    ${ins.notes.map(n=>`<div class="quote"><b>${esc(n.name)}</b><br>“${esc(n.text)}”<cite>${esc(n.attribution)}</cite></div>`).join('')}</div>`:'';
  const failed=(INS.data.formulas||[]).filter(f=>f.status==='rejected');
  const fails=failed.length?`<div class="card"><details><summary style="cursor:pointer;min-height:44px;display:flex;align-items:center;gap:10px;font:700 19px var(--font-d)"><i data-lucide="flask-conical"></i>${esc(t('failH'))} (${failed.length})</summary>
    <div style="margin-top:12px">${failed.map(f=>`<div class="fact"><div class="t"><b>${esc(f.name)}</b><small><code>${esc(f.expression)}</code></small><small>${esc((f.evidence||{}).reason||'')}</small></div><span class="chip crit">${f.source==='seed'?'ours':'model idea'}</span></div>`).join('')}</div></details></div>`:'';
  root.innerHTML=hero+(tiles?`<div class="grid4">${tiles}</div>`:'')
    +`<div class="card"><div class="card-h"><span class="ico"><i data-lucide="lightbulb"></i></span><div class="grow"><h2>${esc(t('insH'))}</h2></div></div>${found}</div>`+market+notes+fails
    +`<p class="muted" style="text-align:center">${esc(t('caNote'))}</p>`;
  icons();bindIns();
}
function emptySvg(){return `<svg viewBox="0 0 140 100" role="img" aria-label="" aria-hidden="true"><rect x="10" y="60" width="18" height="30" rx="4" fill="var(--teal-soft)"/><rect x="36" y="44" width="18" height="46" rx="4" fill="var(--teal)" opacity=".5"/><rect x="62" y="28" width="18" height="62" rx="4" fill="var(--teal)"/><rect x="88" y="50" width="18" height="40" rx="4" fill="var(--gold)" opacity=".7"/><circle cx="118" cy="22" r="14" fill="var(--gold-soft)"/><path d="M112 22l4 4 8-9" stroke="var(--gold-d)" stroke-width="3" fill="none" stroke-linecap="round"/></svg>`;}
function bindIns(){
  const r=$('insRefresh');if(r)r.onclick=async()=>{
    INS.busy=true;renderInsights();
    try{await post('/sim/close',{month:CL.month,analyse:true});toast(t('updated'));}catch{toast(t('oops'),'err');}
    INS.busy=false;await loadInsights();};
  const a=$('goClose');if(a)a.onclick=()=>setRoute('close');const b=$('goChat');if(b)b.onclick=()=>setRoute('chat');
}

/* ---------- start ---------- */
applyTheme(localStorage.getItem('munim_theme')||null);
setLang(lang);setState('idle');icons();loadStatus();loadBooks();loadDocs();loadReady();loadProfile();setInterval(loadStatus,20000);
setRoute(location.hash.slice(1)||'chat',false);
