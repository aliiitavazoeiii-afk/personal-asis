'use strict';
const $=id=>document.getElementById(id);
const state={items:[],kind:'note',filter:'all',editing:null,recording:false,mediaRecorder:null,chunks:[],started:0,timer:null,ai:false,pendingNative:false,mediaStream:null,uploadTimer:null,recordStartGuard:null};
const fa=n=>String(n).replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
const kindLabel={reminder:'یادآوری',task:'کار',note:'یادداشت',idea:'ایده'};
async function api(path,opts={}){
  const controller=new AbortController();
  const wait=path==='/api/transcribe'?110000:45000;
  const timeout=setTimeout(()=>controller.abort(),wait);
  try{
    const response=await fetch(path,{
      credentials:'same-origin',...opts,signal:controller.signal,
      headers:opts.body instanceof FormData?{}:{'Content-Type':'application/json',...(opts.headers||{})}
    });
    let data={};try{data=await response.json()}catch{}
    if(!response.ok){
      if(response.status===401&&path!='/api/login')showLogin();
      throw new Error(typeof data.detail==='string'?data.detail:'خطای سرور: '+response.status);
    }
    return data;
  }catch(e){
    if(e.name==='AbortError')throw new Error('زمان پاسخ سرور به پایان رسید؛ اتصال اینترنت را بررسی کن');
    if(e instanceof TypeError)throw new Error('اتصال به سرور برقرار نشد؛ اینترنت گوشی را بررسی کن');
    throw e;
  }finally{clearTimeout(timeout)}
}
function toast(msg){const e=$('toast');e.textContent=msg;e.hidden=false;clearTimeout(e._t);e._t=setTimeout(()=>e.hidden=true,3600)}
function showLogin(){$('login-screen').hidden=false;$('app').hidden=true}
function showApp(){$('login-screen').hidden=true;$('app').hidden=false;view('home')}
function view(name){document.querySelectorAll('.view').forEach(v=>v.classList.toggle('is-active',v.id==='view-'+name));if(name==='list')renderList()}
function setKind(kind){state.kind=kind;document.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('active',b.dataset.kind===kind));$('due-wrap').hidden=kind!=='reminder';$('save-item').textContent=kind==='reminder'?'ثبت یادآوری':`ثبت ${kindLabel[kind]}`;}
function localDateValue(value){if(!value)return'';const d=new Date(value);const pad=x=>String(x).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`}
function openReview({kind='note',title='',detail='',due_at=null,editing=null,clarification=null}={}){state.editing=editing;$('review-title').value=title;$('review-detail').value=detail;$('due-input').value=localDateValue(due_at);setKind(kind);$('suggestion-content').textContent=clarification||'نوع ثبت و جزئیات را بررسی کن، سپس دکمه ثبت را بزن.';view('review')}
function formatDate(iso){if(!iso)return'';const date=new Date(iso);return new Intl.DateTimeFormat('fa-IR',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(date)}
function createCard(item){const card=document.createElement('div');card.className='item-card'+(item.status==='done'?' done':'');const status=document.createElement('button');status.className='item-status'+(item.status==='done'?' done':'');status.textContent=item.status==='done'?'✓':'';status.setAttribute('aria-label',item.status==='done'?'برگرداندن به انجام‌نشده':'تکمیل کار');status.onclick=()=>changeStatus(item);const info=document.createElement('div');info.className='item-info';const name=document.createElement('p');name.className='item-title';name.textContent=item.title;const date=document.createElement('p');date.className='item-date';date.textContent=item.due_at?formatDate(item.due_at):kindLabel[item.kind];info.append(name,date);const badge=document.createElement('span');badge.className='item-icon';badge.textContent={reminder:'♧',task:'✓',note:'▤',idea:'✧'}[item.kind];const edit=document.createElement('button');edit.className='item-actions';edit.textContent='⋮';edit.setAttribute('aria-label','ویرایش یا حذف');edit.onclick=()=>{const action=confirm('برای ویرایش «تأیید» و برای لغو «انصراف» را بزن. برای حذف، مورد را از صفحه ویرایش حذف کن.');if(action)openReview({...item,editing:item.id})};card.append(status,info,badge,edit);return card}
async function changeStatus(item){try{const x=await api(`/api/items/${item.id}`,{method:'PATCH',body:JSON.stringify({status:item.status==='done'?'open':'done'})});state.items=state.items.map(a=>a.id===x.id?x:a);renderList();syncNative()}catch(e){toast(e.message)}}
function renderList(){const target=$('items-list');target.replaceChildren();const term=$('list-search').value.trim();let list=state.items.filter(x=>(state.filter==='all'||x.kind===state.filter)&&(!term||x.title.includes(term)||x.detail.includes(term)));list.sort((a,b)=>(a.status==='done')-(b.status==='done')||(a.due_at||'9999').localeCompare(b.due_at||'9999')||b.created_at.localeCompare(a.created_at));if(!list.length){const msg=document.createElement('p');msg.className='empty';msg.textContent='هنوز موردی ثبت نشده. روی میکروفون بزن و شروع کن.';target.append(msg);return}const groups=[['امروز',list.filter(x=>x.due_at&&new Date(x.due_at).toDateString()===new Date().toDateString())],['کارها و یادداشت‌ها',list.filter(x=>!x.due_at)],['برنامه‌های آینده',list.filter(x=>x.due_at&&new Date(x.due_at).toDateString()!==new Date().toDateString())]];for(const [name,items] of groups){if(!items.length)continue;const title=document.createElement('h3');title.className='group-title';title.textContent=name;target.append(title);items.forEach(x=>target.append(createCard(x)))}}
function syncNative(){if(typeof Native==='undefined')return;const upcoming=state.items.filter(x=>x.kind==='reminder'&&x.status==='open'&&x.due_at&&new Date(x.due_at).getTime()>Date.now()).sort((a,b)=>new Date(a.due_at)-new Date(b.due_at)).slice(0,100).map(x=>({id:x.id,title:x.title,epoch:new Date(x.due_at).getTime()}));try{Native.syncReminders(JSON.stringify(upcoming))}catch(e){console.error('Native reminders:',e)}}
async function loadItems(){const data=await api('/api/items');state.items=data.items;renderList();syncNative()}
async function analyze(text){if(!text.trim()){toast('متنی برای ثبت پیدا نشد');return}openReview({title:text});$('suggestion-content').textContent='در حال تشخیص نوع درخواست...';try{const data=await api('/api/parse',{method:'POST',body:JSON.stringify({text,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Tehran',now:new Date().toISOString()})});openReview({kind:data.kind,title:data.title,detail:data.detail,due_at:data.due_at,clarification:data.clarification});if(data.needs_clarification)toast('زمان دقیق برای یادآوری مشخص نشده است')}catch(e){toast('متن ثبت شد اما تحلیل خودکار ممکن نشد');openReview({title:text})}}
async function save(){const title=$('review-title').value.trim();if(!title){toast('متن نمی‌تواند خالی باشد');return}let due=null;if(state.kind==='reminder'){const v=$('due-input').value;if(!v){toast('لطفاً روز و ساعت یادآوری را مشخص کن');return}const d=new Date(v);if(isNaN(d.getTime())||d.getTime()<=Date.now()){toast('زمان یادآوری باید در آینده باشد');return}due=d.toISOString()}const payload={kind:state.kind,title,detail:$('review-detail').value.trim(),due_at:due};const btn=$('save-item');btn.disabled=true;try{let saved;if(state.editing){saved=await api(`/api/items/${state.editing}`,{method:'PATCH',body:JSON.stringify(payload)});state.items=state.items.map(i=>i.id===saved.id?saved:i)}else{saved=await api('/api/items',{method:'POST',body:JSON.stringify(payload)});state.items.unshift(saved)}toast('با موفقیت ثبت شد');state.editing=null;syncNative();view('list')}catch(e){toast(e.message)}finally{btn.disabled=false}}
function recordTime(){if(!state.recording)return;const sec=Math.floor((Date.now()-state.started)/1000);$('record-timer').textContent=fa(`${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`);if(sec>=60)stopRecording()}
function startClock(){state.recording=true;state.started=Date.now();$('record-timer').textContent='۰۰:۰۰';clearInterval(state.timer);state.timer=setInterval(recordTime,500);view('record')}
function closeClock(){state.recording=false;clearInterval(state.timer)}
function showRecordingError(message){
  clearTimeout(state.uploadTimer);
  clearTimeout(state.recordStartGuard);
  closeClock();
  state.pendingNative=false;
  $('stop-record').disabled=false;
  $('record-status').textContent='خطا در پردازش صدا';
  const help=$('record-help');
  help.hidden=false;
  help.textContent=(typeof Native!=='undefined'
    ? 'این APK ممکن است در انتقال صدا مشکل داشته باشد. بدون دانلود APK، همین آدرس را در Chrome گوشی باز کن و از منو به صفحه اصلی اضافه کن.'
    : 'اتصال و دسترسی میکروفن را بررسی کن و دوباره تلاش کن. در Chrome آدرس HTTPS برنامه را باز کن.');
  toast(message);
}
async function startRecording(){
  if(state.recording||state.pendingNative)return;
  $('record-help').hidden=true;
  try{
    if(typeof Native!=='undefined'&&Native.startRecording){
      state.pendingNative=true;
      view('record');
      $('record-status').textContent='در حال آماده‌سازی میکروفن...';
      $('stop-record').disabled=true;
      clearTimeout(state.recordStartGuard);
      state.recordStartGuard=setTimeout(()=>{
        if(state.pendingNative&&!state.recording)
          showRecordingError('پاسخی از میکروفن APK دریافت نشد؛ نسخه وب را در Chrome باز کن.');
      },12000);
      Native.startRecording();
      return;
    }
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){
      throw new Error('مرورگر از ضبط صدا پشتیبانی نمی‌کند؛ از Chrome اندروید استفاده کن.');
    }
    const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    state.mediaStream=stream;
    state.chunks=[];
    const formats=['audio/webm;codecs=opus','audio/webm','audio/mp4'];
    const mime=formats.find(x=>MediaRecorder.isTypeSupported(x))||'';
    const mr=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);
    state.mediaRecorder=mr;
    mr.ondataavailable=e=>{if(e.data?.size)state.chunks.push(e.data)};
    mr.onerror=()=>{stream.getTracks().forEach(t=>t.stop());showRecordingError('ضبط صدا توسط مرورگر متوقف شد')};
    mr.onstop=()=>{
      stream.getTracks().forEach(t=>t.stop());
      state.mediaStream=null;
      const type=mr.mimeType||'audio/webm';
      const ext=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';
      const blob=new Blob(state.chunks,{type});
      state.chunks=[];
      if(blob.size<300){showRecordingError('صدای کافی ضبط نشد؛ دوباره امتحان کن');return}
      sendAudio(blob,'voice.'+ext);
    };
    mr.start(1000);
    $('record-status').textContent='در حال گوش دادن...';
    startClock();
  }catch(e){
    state.mediaStream?.getTracks().forEach(t=>t.stop());
    state.mediaStream=null;
    view('record');
    showRecordingError(e.message||'اجازه میکروفن صادر نشد');
  }
}
function stopRecording(){
  if(!state.recording)return;
  closeClock();
  $('record-status').textContent='در حال تبدیل صدا به متن...';
  $('stop-record').disabled=true;
  if(typeof Native!=='undefined'&&Native.stopRecording){
    Native.stopRecording();
    clearTimeout(state.uploadTimer);
    state.uploadTimer=setTimeout(()=>{
      if($('record-status').textContent==='در حال تبدیل صدا به متن...')
        showRecordingError('APK از تبدیل صدا پاسخی نداد؛ در Chrome نسخه وب را استفاده کن.');
    },115000);
    return;
  }
  if(state.mediaRecorder&&state.mediaRecorder.state!=='inactive')state.mediaRecorder.stop();
  else showRecordingError('فایل ضبط‌شده در مرورگر پیدا نشد');
}
async function sendAudio(blob,filename){
  $('record-status').textContent='در حال تبدیل صدا به متن...';
  const form=new FormData();
  form.append('audio',blob,filename);
  try{
    const data=await api('/api/transcribe',{method:'POST',body:form});
    if(!data.text?.trim())throw new Error('هیچ متنی از صدا تشخیص داده نشد');
    view('home');
    await analyze(data.text);
  }catch(e){
    view('record');
    showRecordingError('تبدیل صدا ناموفق بود: '+e.message);
  }finally{
    $('stop-record').disabled=false;
  }
}
window.PersonalAssist={
  // Compatibility with the original APK. The preferred path for web is
  // MediaRecorder -> authenticated multipart upload with no WebView bridge.
  onNativeAudio(base64){
    try{
      const binary=atob(base64);
      const bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
      sendAudio(new Blob([bytes],{type:'audio/mp4'}),'voice.m4a');
    }catch(e){showRecordingError('پردازش فایل ضبط‌شده ممکن نشد')}
  },
  onNativeTranscription(text){
    clearTimeout(state.uploadTimer);
    clearTimeout(state.recordStartGuard);
    state.pendingNative=false;
    $('stop-record').disabled=false;
    if(typeof text==='string'&&text.trim()){
      view('home');analyze(text);
    }else{showRecordingError('متنی از صدا تشخیص داده نشد')}
  },
  onNativeUploadError(message){
    showRecordingError('خطای ارسال صدا: '+String(message||'ارتباط برقرار نشد'))
  },
  nativeStatus(status){
    clearTimeout(state.recordStartGuard);
    state.pendingNative=false;
    if(status==='recording'){
      $('stop-record').disabled=false;
      $('record-status').textContent='در حال گوش دادن...';
      startClock();return;
    }
    showRecordingError(status==='permission_denied'
      ? 'اجازه استفاده از میکروفن را در تنظیمات گوشی فعال کن'
      : 'ضبط صدا در APK امکان‌پذیر نشد');
  }
};
$('login-form').onsubmit=async e=>{e.preventDefault();$('login-error').hidden=true;try{const r=await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});if(r.ok){$('password').value='';showApp();loadItems()}}catch(err){$('login-error').textContent=err.message;$('login-error').hidden=false}};
$('mic-button').onclick=startRecording;$('nav-mic').onclick=startRecording;$('stop-record').onclick=stopRecording;$('close-record').onclick=()=>{if(state.recording)stopRecording();view('home')};$('save-item').onclick=save;$('back-review').onclick=()=>view('home');$('back-list').onclick=()=>view('home');$('home-menu').onclick=()=>view('list');$('go-list').onclick=()=>view('list');$('settings-btn').onclick=()=>view('settings');$('back-settings').onclick=()=>view('home');$('search-btn').onclick=()=>{$('list-search').hidden=!$('list-search').hidden;if(!$('list-search').hidden)$('list-search').focus()};$('list-search').oninput=renderList;
document.querySelectorAll('[data-quick]').forEach(b=>b.onclick=()=>openReview({kind:b.dataset.quick}));document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>setKind(b.dataset.kind));document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');state.filter=b.dataset.filter;renderList()});document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.nav==='home')view('home');else if(b.dataset.nav==='reminder'){state.filter='reminder';view('list')}else if(b.dataset.nav==='more')view('settings');else{state.filter='all';view('list')}});
if(typeof Native!=='undefined'&&Native.configureServer){$('change-server').hidden=false;$('change-server').onclick=()=>Native.configureServer()}
$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST',body:'{}'})}finally{showLogin()}};
(async()=>{try{const me=await api('/api/me');state.ai=me.ai_enabled;$('ai-status').textContent=state.ai?'پردازش فارسی با هوش مصنوعی فعال است.':'کلید OpenAI هنوز تنظیم نشده است؛ یادداشت و کارها قابل استفاده‌اند.';showApp();await loadItems()}catch(e){showLogin()}})();

let installPrompt=null;
window.addEventListener('beforeinstallprompt',event=>{
  event.preventDefault();
  installPrompt=event;
  $('install-pwa').hidden=false;
});
$('install-pwa').onclick=async()=>{
  if(!installPrompt)return;
  const event=installPrompt;
  installPrompt=null;
  $('install-pwa').hidden=true;
  await event.prompt();
};
if('serviceWorker' in navigator && location.protocol==='https:'){
  navigator.serviceWorker.register('/sw.js').catch(()=>{});
}
