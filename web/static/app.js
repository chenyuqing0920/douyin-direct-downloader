'use strict';
let csrf = '', timer, lastSnapshot = '', noticeTimer;
const transfers = new Map();
const $ = id => document.getElementById(id);
// Keep frontend-only updates compatible with templates cached by a running EXE.
document.title='随手存 · 抖音视频下载';
document.querySelector('meta[name="theme-color"]').setAttribute('content','#fafafa');
for(const [selector,text] of [
  ['.intro h1','抖音视频下载'],['.description','粘贴链接或分享文案，保存喜欢的视频。'],
  ['#login-panel h2','输入访问密码'],['#login-panel .panel-top p','验证后即可开始使用'],
  ['#login-panel .hint','请使用服务提供者分享的密码。'],['#workspace .panel h2','视频链接'],
  ['#workspace .panel-top p','支持完整分享文案，也可以一次粘贴多条链接'],
  ['.empty h3','还没有解析记录'],['.empty p','粘贴链接，开始保存第一条视频'],['footer','手机与电脑均可使用']
]){const el=document.querySelector(selector);if(el)el.textContent=text;}
$('login-button').replaceChildren(document.createTextNode('进入'),node('span','','→'));
document.querySelector('.connection').lastChild.textContent='服务在线';
const states = {queued:'排队中',resolving:'解析中',ready:'可下载',failed:'未完成',cancelled:'已取消'};
function notify(text) { $('notice').textContent=text; $('notice').hidden=false; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>$('notice').hidden=true,10000); }
async function api(path, options={}) {
  const headers={...(options.body?{'Content-Type':'application/json'}:{}), ...(csrf?{'X-CSRF-Token':csrf}:{}),...options.headers};
  const response=await fetch(path,{...options,headers,cache:'no-store',credentials:'same-origin'});
  const data=await response.json();
  if(!response.ok){if(response.status===401 && path!=='/api/login')showLogin();throw new Error(data.error||'连接失败，请稍后重试');}
  return data;
}
function showLogin(){csrf='';clearTimeout(timer);$('login-panel').hidden=false;$('workspace').hidden=true;}
function showWorkspace(token){csrf=token;$('login-panel').hidden=true;$('workspace').hidden=false;refresh();}
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function size(value){return (value/1048576).toFixed(1)+' MB';}
function transferLabel(key, text){
  const card=document.querySelector('[data-key="'+key+'"]');
  if(card){const button=card.querySelector('.save-button');if(button){button.textContent=text;button.disabled=transfers.has(key);}const cancel=card.querySelector('.cancel-client');if(cancel)cancel.hidden=!transfers.has(key);const small=card.querySelector('.job-footer small');if(small)small.textContent=transfers.has(key)?'此设备正在接收':'直连下载';}
}
async function directDownload(job){
  if(transfers.has(job.id))return;
  const transfer={controller:new AbortController(),cancelled:false};transfers.set(job.id,transfer);transferLabel(job.id,'准备直连…');
  try{
    const data=await api('/api/jobs/'+job.id+'/direct',{signal:transfer.controller.signal});
    let blob;
    for(const url of data.urls.slice(0,5)){
      if(transfer.cancelled)throw new Error('已取消下载');
      transfer.controller=new AbortController();let idle;
      const resetTimeout=()=>{clearTimeout(idle);idle=setTimeout(()=>transfer.controller.abort(),30000);};resetTimeout();
      try{
        const response=await fetch(url,{mode:'cors',credentials:'omit',referrerPolicy:'no-referrer',cache:'no-store',signal:transfer.controller.signal});
        if(response.status!==200)throw new Error('源站拒绝直连');
        const type=(response.headers.get('Content-Type')||'').toLowerCase();
        if(!type.includes('video/')&&!type.includes('octet-stream'))throw new Error('源站没有返回视频');
        const total=Number(response.headers.get('Content-Length')||0),limit=128*1024*1024;
        if(total>limit){const e=new Error('视频较大，请点击“源站打开”，在视频页面保存。');e.oversized=true;throw e;}
        const reader=response.body.getReader(),parts=[];let received=0;
        while(true){const {done,value}=await reader.read();if(done)break;resetTimeout();parts.push(value);received+=value.length;
          if(received>limit){const e=new Error('视频较大，请点击“源站打开”，在视频页面保存。');e.oversized=true;throw e;}
          transferLabel(job.id,total?'接收 '+Math.floor(received/total*100)+'%':'接收 '+size(received));}
        if(!received||(total&&received!==total))throw new Error('源站传输不完整');
        blob=new Blob(parts,{type:'video/mp4'});break;
      }catch(e){transfer.controller.abort();if(e.oversized||transfer.cancelled)throw e;}
      finally{clearTimeout(idle);}
    }
    if(!blob)throw new Error('此源站暂不允许网页直连读取。请尝试“源站打开”后保存；仍失败时请重新解析。电脑不会代为转发。');
    const url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download=data.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    notify('视频已由此设备直接接收，请在浏览器下载列表确认保存。');
  }catch(e){notify(transfer.cancelled?'已取消本设备的下载。':e.message);}
  finally{transfers.delete(job.id);transferLabel(job.id,'直接下载 ↓');}
}
function render(jobs){
  const snapshot=JSON.stringify(jobs);if(lastSnapshot===snapshot)return;lastSnapshot=snapshot;
  $('job-count').textContent=jobs.length;
  if(!jobs.length)return;
  $('jobs').replaceChildren();
  for(const job of jobs){
    const card=node('article','job');card.dataset.state=job.state;card.dataset.key=job.id;
    const top=node('div','job-top'), icon=node('span','job-icon',job.state==='ready'?'✓':'↓'), info=node('div','job-info');
    info.append(node('h3','',job.title),node('p','job-message',job.message));top.append(icon,info,node('span','job-status',states[job.state]||job.state));card.append(top);
    const footer=node('div','job-footer'),actions=node('div','job-actions'),secondary=node('div','job-secondary');
    footer.append(node('small','',job.state==='ready'?'直连下载':'单个视频作品'));
    if(job.state==='ready'){
      const preview=node('button','preview-button','预览');preview.type='button';preview.onclick=()=>{$('preview-video').src='/files/'+job.id;$('preview-dialog').showModal();};
      const save=node('button','save-button',transfers.has(job.id)?'设备接收中…':'直接下载 ↓');save.type='button';save.disabled=transfers.has(job.id);save.onclick=()=>directDownload(job);actions.append(preview,save);
      const cancel=node('button','text-button cancel-client','取消接收');cancel.hidden=!transfers.has(job.id);cancel.onclick=()=>{const t=transfers.get(job.id);if(t){t.cancelled=true;t.controller.abort();}};secondary.append(cancel);
      const origin=node('a','text-button','源站打开 ↗');origin.href='/files/'+job.id;origin.target='_blank';origin.rel='noopener noreferrer';origin.referrerPolicy='no-referrer';secondary.append(origin);
      const retry=node('button','text-button','重新解析');retry.onclick=async()=>{try{await api('/api/jobs',{method:'POST',body:JSON.stringify({text:job.link})});refresh();}catch(e){notify(e.message);}};secondary.append(retry);
    }else if(['queued','resolving'].includes(job.state)){
      const cancel=node('button','text-button','取消');cancel.onclick=async()=>{try{await api('/api/jobs/'+job.id+'/cancel',{method:'POST',body:'{}'});refresh();}catch(e){notify(e.message);}};actions.append(cancel);
    }else{const retry=node('button','text-button','重试');retry.onclick=async()=>{try{await api('/api/jobs',{method:'POST',body:JSON.stringify({text:job.link})});refresh();}catch(e){notify(e.message);}};actions.append(retry);}
    footer.append(actions);card.append(footer);if(secondary.childElementCount)card.append(secondary);$('jobs').append(card);
  }
}
async function refresh(){clearTimeout(timer);if(!csrf)return;try{const data=await api('/api/jobs');render(data.jobs);document.querySelector('.connection').lastChild.textContent='服务在线';}catch(e){if(csrf){notify('连接中断，请确认电脑远程版仍在运行。');document.querySelector('.connection').lastChild.textContent='连接中断';}}finally{if(csrf)timer=setTimeout(refresh,2500);}}
$('login-form').onsubmit=async event=>{event.preventDefault();$('login-button').disabled=true;try{const data=await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});$('password').value='';showWorkspace(data.csrf);}catch(e){notify(e.message);}finally{$('login-button').disabled=false;}};
$('toggle-password').onclick=()=>{const hidden=$('password').type==='password';$('password').type=hidden?'text':'password';$('toggle-password').textContent=hidden?'隐藏':'显示';};
$('download-form').onsubmit=async event=>{event.preventDefault();$('submit-button').disabled=true;try{await api('/api/jobs',{method:'POST',body:JSON.stringify({text:$('share-text').value})});$('share-text').value='';notify('正在解析。完成后点击“直接下载”，由你的设备直连视频源站。');await refresh();}catch(e){notify(e.message);}finally{$('submit-button').disabled=false;}};
$('clear-button').onclick=()=>{$('share-text').value='';$('share-text').focus();};
$('refresh-button').onclick=refresh;
$('logout-button').onclick=async()=>{try{await api('/api/logout',{method:'POST',body:'{}'});showLogin();}catch(e){notify(e.message);}};
$('close-preview').onclick=()=>$('preview-dialog').close();
$('preview-dialog').addEventListener('close',()=>{$('preview-video').pause();$('preview-video').removeAttribute('src');$('preview-video').load();});
$('preview-video').addEventListener('error',()=>notify('源站拒绝直连或地址已过期，请重新解析；此模式不会使用电脑转发。'));
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&csrf)refresh();});
api('/api/session').then(data=>showWorkspace(data.csrf)).catch(()=>showLogin());
