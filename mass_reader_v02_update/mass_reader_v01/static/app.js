'use strict';
const T={
 en:{brand:'Mass Reader',brandSub:'Workspace control center',workspaces:'Workspaces',welcomeHead:'Map any file system, progressively.',welcomeBody:'Create a workspace for a company, department, project, drive, or folder group. Define its boundaries, then start a resumable inventory.',createWorkspace:'Create workspace',workspace:'WORKSPACE',refresh:'Refresh',addPath:'+ Add path',tabScope:'Scope manager',tabProgress:'Progress & runs',tabFiles:'File inventory',scopeHead:'Mapped source paths',scopeHint:'Each path has its own recursion, inclusions, exclusions and specific overrides. No drive is scanned until you start.',scopeLogic:'Scope precedence',scopeLogicBody:'Explicit overrides win over exclusions. Excluded folders are pruned, except ancestors of explicitly allowed files. Include patterns filter files; all observed file types are recorded.',runHead:'Scan & resume',runHint:'Choose 100 files for a small batch, then resume from its checkpoint. Choose 0 for an unrestricted scan.',batchSize:'Files per batch (0 = all)',startScan:'Start new scan',resumeScan:'Resume',pauseScan:'Pause',cancelScan:'Cancel run',runHistory:'Run history',runId:'Run ID',status:'Status',files:'Files',startTime:'Started (UTC)',filesHead:'File inventory',filesHint:'All observed file types, including unsupported and excluded files. This phase does not read document content.',searchPlaceholder:'Search name or path',search:'Search',filename:'File',format:'Type',decision:'Scope decision',changed:'Latest scan',relativePath:'Relative path',name:'Name',description:'Description',cancel:'Cancel',create:'Create',save:'Save scope',scopeName:'Scope label',rootPath:'Absolute folder or file path',recursive:'Recursive scan',enabled:'Enabled',depth:'Maximum depth (-1 = all)',include:'Include patterns — one per line',exclude:'Exclude patterns — one per line',override:'Specific allow overrides — one per line',patternsHelp:'Examples: *.xlsx · Archive/** · ~$* · Archive/Approved.xlsx. Allow overrides can pass an excluded parent.',noScopes:'No paths yet. Add a path to define this workspace.',edit:'Edit',delete:'Remove',yesDelete:'Remove this path rule? Existing run evidence is preserved.',scopedFiles:'Files observed',pathScopes:'Path scopes',runs:'Runs',latestRun:'Latest run',uncertain:'Not evaluated',notStarted:'Not started',fileTypes:'Known formats',folders:'Folders',foldersProgress:'Folder progress',noRuns:'No runs yet.',resumeNote:'Paused scans retain the file position and folder queue.',noFiles:'No files inventoried yet.',folderDetails:'Discovered folder queue',exportArea:'Download area progress CSV',exportFolders:'Download folder status CSV',notSupported:'Unsupported / unknown',included:'Included',excluded:'Excluded',outOfScope:'Outside include',events:'Run events',errors:'Inaccessible paths',folder:'Folder',observed:'Seen files',scope:'Scope',budgetReached:'Batch limit reached. Resume to continue.',done:'Completed',empty:'—',runProgress:'Current run',confirmCancel:'Cancel this run? Its inventory and history will remain.'},
 fa:{brand:'خوانشگر انبوه',brandSub:'مدیریت محدوده‌های بررسی',workspaces:'فضاهای کاری',welcomeHead:'هر فضای فایلی را گام‌به‌گام نقشه‌برداری کنید.',welcomeBody:'برای شرکت، بخش، پروژه یا مجموعه‌ای از پوشه‌ها یک فضای کاری بسازید؛ حدود آن را تعیین کنید و پیمایش قابل‌ادامه را آغاز کنید.',createWorkspace:'ایجاد فضای کاری',workspace:'فضای کاری',refresh:'به‌روزرسانی',addPath:'+ افزودن مسیر',tabScope:'مدیریت محدوده',tabProgress:'پیشرفت و اجراها',tabFiles:'فهرست فایل‌ها',scopeHead:'مسیرهای تعریف‌شده',scopeHint:'برای هر مسیر می‌توان پیمایش بازگشتی، الگوهای شمول و استثنا و مجوزهای موردی تنظیم کرد. تا شروع نکنید هیچ مسیری پیمایش نمی‌شود.',scopeLogic:'اولویت قواعد',scopeLogicBody:'مجوز موردی بر استثنا مقدم است. پوشه‌های مستثنا پیمایش نمی‌شوند مگر برای رسیدن به مسیر مجاز مشخص. الگوهای شمول بر فایل‌ها اعمال می‌شوند و همهٔ انواع فایل‌های مشاهده‌شده ثبت می‌شوند.',runHead:'پیمایش و ادامه',runHint:'برای بررسی تدریجی می‌توانید هر بار ۱۰۰ فایل را انتخاب کنید و سپس از همان نقطه ادامه دهید. صفر یعنی بدون محدودیت.',batchSize:'حد فایل در هر مرحله (صفر = همه)',startScan:'شروع اجرای جدید',resumeScan:'ادامه',pauseScan:'توقف موقت',cancelScan:'لغو اجرا',runHistory:'سوابق اجرا',runId:'شناسهٔ اجرا',status:'وضعیت',files:'فایل‌ها',startTime:'زمان شروع (UTC)',filesHead:'فهرست فایل‌های شناخته‌شده',filesHint:'تمام قالب‌های دیده‌شده، حتی ناشناخته و مستثنا. در این مرحله محتوای اسناد خوانده نمی‌شود.',searchPlaceholder:'جست‌وجو در نام و مسیر',search:'جست‌وجو',filename:'فایل',format:'نوع',decision:'وضعیت محدوده',changed:'آخرین بررسی',relativePath:'مسیر نسبی',name:'نام',description:'شرح',cancel:'انصراف',create:'ایجاد',save:'ذخیرهٔ محدوده',scopeName:'عنوان محدوده',rootPath:'مسیر کامل پوشه یا فایل',recursive:'پیمایش بازگشتی',enabled:'فعال',depth:'حد عمق (۱- = نامحدود)',include:'الگوهای شمول — هر خط یک الگو',exclude:'الگوهای استثنا — هر خط یک الگو',override:'مجوزهای موردی — هر خط یک الگو',patternsHelp:'نمونه: *.xlsx · Archive/** · ~$* · Archive/Approved.xlsx. مجوز موردی می‌تواند از پوشهٔ مستثنا عبور کند.',noScopes:'هنوز مسیری تعریف نشده است. یک مسیر اضافه کنید.',edit:'ویرایش',delete:'حذف',yesDelete:'این قاعدهٔ مسیر حذف شود؟ سوابق اجرا حفظ می‌شوند.',scopedFiles:'فایل‌های ثبت‌شده',pathScopes:'محدوده‌ها',runs:'اجراها',latestRun:'آخرین اجرا',uncertain:'ارزیابی‌نشده',notStarted:'آغاز نشده',fileTypes:'قالب‌های شناخته‌شده',folders:'پوشه‌ها',foldersProgress:'پیشرفت پوشه‌ها',noRuns:'هنوز اجرایی ثبت نشده است.',resumeNote:'پیمایش متوقف‌شده موقعیت فایل‌ها و صف پوشه‌ها را حفظ می‌کند.',noFiles:'هنوز فایلی ثبت نشده است.',folderDetails:'صف پوشه‌های شناسایی‌شده',exportArea:'دریافت گزارش پیشرفت محدوده‌ها',exportFolders:'دریافت وضعیت پوشه‌ها',notSupported:'ناشناخته / پشتیبانی‌نشده',included:'مشمول',excluded:'مستثنا',outOfScope:'خارج از الگوی شمول',events:'رویدادهای اجرا',errors:'مسیرهای غیرقابل‌دسترسی',folder:'پوشه',observed:'فایل‌های مشاهده‌شده',scope:'محدوده',budgetReached:'حد مرحله رسید؛ برای ادامه از دکمه ادامه استفاده کنید.',done:'تمام‌شده',empty:'—',runProgress:'اجرای فعلی',confirmCancel:'اجرای فعلی لغو شود؟ سوابق و فهرست فایل‌ها حفظ می‌شوند.'}
};
const $=id=>document.getElementById(id);
const state={lang:localStorage.getItem('mr_lang')||'fa',wid:Number(localStorage.getItem('mr_wid')||0),detail:null,runId:null,tab:'scope',fileOffset:0,scopeEditing:null,sessionTimer:null,pollPending:false};
const tr=k=>(T[state.lang][k]||T.en[k]||k);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(s,bad=false){const e=$('toast');e.textContent=s;e.className=bad?'error':'';e.style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>e.style.display='none',4500)}
async function api(path,method='GET',payload){const o={method,headers:{}};if(payload!==undefined){o.headers['Content-Type']='application/json';o.body=JSON.stringify(payload)}let r=await fetch(path,o);let data=await r.json();if(!r.ok)throw Error(data.error||r.statusText);return data}
function translate(){document.documentElement.lang=state.lang;document.documentElement.dir=state.lang==='fa'?'rtl':'ltr';document.body.dir=document.documentElement.dir;document.querySelectorAll('[data-t]').forEach(n=>n.textContent=tr(n.dataset.t));document.querySelectorAll('[data-place]').forEach(n=>n.placeholder=tr(n.dataset.place));$('language').textContent=state.lang==='fa'?'English':'فارسی';}
function tag(v){let c=['COMPLETED','INCLUDED','DONE','UNCHANGED'].includes(v)?'good':['ERROR','COMPLETED_WITH_ERRORS','EXCLUDED','CANCELLED'].includes(v)?'bad':'warn';return `<span class="tag ${c}">${esc(v||'—')}</span>`}
function num(x){return Number(x||0).toLocaleString(state.lang==='fa'?'fa-IR':'en-US')}
function time(x){return x?esc(x.replace('T',' ').slice(0,19)):'—'}
async function loadWorkspaces(){const x=await api('/api/workspaces');$('workspaceList').innerHTML=x.map(w=>`<button class="workspace-item ${w.id===state.wid?'selected':''}" data-id="${w.id}"><b>${esc(w.name)}</b><small>${num(w.scope_count)} ${tr('pathScopes')} · ${num(w.file_count)} ${tr('files')}</small></button>`).join('');document.querySelectorAll('.workspace-item').forEach(b=>b.onclick=()=>chooseWorkspace(Number(b.dataset.id)));if(state.wid&&!x.some(w=>w.id===state.wid))state.wid=0;if(!state.wid&&x.length)await chooseWorkspace(x[0].id);else if(!state.wid)showWelcome()}
function showWelcome(){$('welcome').hidden=false;$('workspaceView').hidden=true}
async function chooseWorkspace(id){state.wid=id;localStorage.setItem('mr_wid',String(id));$('welcome').hidden=true;$('workspaceView').hidden=false;await loadDetail();document.querySelectorAll('.workspace-item').forEach(b=>b.classList.toggle('selected',Number(b.dataset.id)===id))}
async function loadDetail(live=false){
 if(!state.wid)return;
 const wid=state.wid;
 const d=await api('/api/workspaces/'+wid);
 if(state.wid!==wid)return;
 state.detail=d;
 $('workspaceTitle').textContent=d.workspace.name;
 $('workspaceDesc').textContent=d.workspace.description||'';
 const last=d.runs[0];
 // Never discard a manually selected run during a periodic update.
 if(!state.runId || (!live && !d.runs.some(r=>r.id===state.runId)))state.runId=(last&&last.id)||null;
 const nFiles=d.extensions.reduce((s,e)=>s+e.n,0);
 const m=[[tr('pathScopes'),d.scopes.length],[tr('scopedFiles'),nFiles],[tr('fileTypes'),d.extensions.length],[tr('latestRun'),last?last.status:tr('notStarted')]];
 if(live && $('metrics').querySelectorAll('.metric').length===m.length){
  const nodes=$('metrics').querySelectorAll('.metric');
  m.forEach(([label,value],i)=>{
    const labelNode=nodes[i].querySelector('label'),valueNode=nodes[i].querySelector('strong');
    const formatted=typeof value==='number'?num(value):String(value);
    if(labelNode.textContent!==String(label))labelNode.textContent=label;
    if(valueNode.textContent!==formatted)valueNode.textContent=formatted;
  });
  for(const row of $('runsTable').querySelectorAll('tr[data-run]')){
   const run=d.runs.find(x=>x.id===row.dataset.run);
   if(!run)continue;
   const cells=row.querySelectorAll('td');
   const status=tag(run.status),files=num(run.processed_files);
   if(cells[1] && cells[1].innerHTML!==status)cells[1].innerHTML=status;
   if(cells[2] && cells[2].textContent!==files)cells[2].textContent=files;
  }
 }else{
  $('metrics').innerHTML=m.map(([l,v])=>`<div class="metric"><label>${esc(l)}</label><strong>${typeof v==='number'?num(v):esc(v)}</strong></div>`).join('');
  renderScopes();renderRunHistory();
 }
 if(state.tab==='progress')await renderRun(live);
 if(state.tab==='files' && !live)await renderFiles();
}

function renderScopes(){const d=state.detail;$('scopeList').innerHTML=d.scopes.length?d.scopes.map(s=>`<div class="scope-card"><div class="scope-title"><h4>${esc(s.label)} ${!s.enabled?tag('DISABLED'):''}</h4><div class="actions"><button class="btn small" data-edit="${s.id}">${tr('edit')}</button><button class="btn small danger" data-remove="${s.id}">${tr('delete')}</button></div></div><div class="scope-path" dir="ltr">${esc(s.root)}</div><div class="scope-meta"><span class="pill">${s.recursive?'Recursive':'Root only'}</span><span class="pill">Depth ${s.max_depth}</span><span class="pill">Include: ${esc(s.include.join(', ')||'*')}</span><span class="pill">Exclude: ${esc(s.exclude.join(', ')||'none')}</span>${s.override.length?`<span class="pill">Overrides: ${esc(s.override.join(', '))}</span>`:''}</div></div>`).join(''):`<div class="card muted">${tr('noScopes')}</div>`;document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>showScope(Number(b.dataset.edit)));document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=async()=>{if(!confirm(tr('yesDelete')))return;try{await api(`/api/workspaces/${state.wid}/scopes/${b.dataset.remove}`,'DELETE');await loadDetail()}catch(e){toast(e.message,true)}})}
function renderRunHistory(){const r=state.detail.runs;$('runsTable').innerHTML=r.length?r.map(run=>`<tr data-run="${esc(run.id)}"><td><button class="btn small" data-run="${esc(run.id)}">${esc(run.id)}</button></td><td>${tag(run.status)}</td><td>${num(run.processed_files)}</td><td dir="ltr">${time(run.started_at)}</td></tr>`).join(''):`<tr><td colspan="4">${tr('noRuns')}</td></tr>`;document.querySelectorAll('button[data-run]').forEach(b=>b.onclick=async()=>{state.runId=b.dataset.run;await renderRun()})}
// Stable dashboard shell: never replace the whole progress panel on a live refresh.
async function renderRun(live=false){
 const runId=state.runId;
 if(!runId){$('runDetail').replaceChildren();return;}
 const data=await api('/api/runs/'+encodeURIComponent(runId));
 const folders=await api('/api/runs/'+encodeURIComponent(runId)+'/folders');
 if(state.runId!==runId || state.tab!=='progress')return;
 const r=data.run,active=['PAUSED','RUNNING','PAUSING','CANCELLING'].includes(r.status);
 $('startScan').disabled=!!state.detail?.runs.some(x=>['RUNNING','PAUSED','PAUSING','CANCELLING'].includes(x.status));
 $('resumeScan').disabled=r.status!=='PAUSED';
 $('pauseScan').disabled=r.status!=='RUNNING';
 $('cancelScan').disabled=!active || r.status==='CANCELLING';
 const done=data.areas.reduce((a,s)=>a+s.folders_done,0);
 const total=data.areas.reduce((a,s)=>a+s.folders_total,0);
 const pct=total?Math.round(done/total*100):0;
 const host=$('runDetail');
 if(host.dataset.renderedRun!==runId || !host.querySelector('#mrRunStatus')){
  // One construction per selected run, never once per poll.
  host.innerHTML=`<div class="card" id="mrRunCard">
   <div class="section-head"><div><h3>${tr('runProgress')} — <code>${esc(r.id)}</code></h3><span id="mrRunStatus"></span></div><span id="mrRunPercent"></span></div>
   <div class="progress"><div id="mrRunBar"></div></div>
   <div class="run-grid" id="mrRunMetrics">${Array.from({length:8},(_,i)=>`<div class="run-metric"><span data-mr-label="${i}"></span><strong data-mr-val="${i}"></strong></div>`).join('')}</div>
   <h4>${tr('foldersProgress')}</h4><div class="scroll"><table><thead><tr><th>${tr('scope')}</th><th>${tr('folders')}</th><th>${tr('observed')}</th><th>${tr('status')}</th></tr></thead><tbody id="mrScopeRows"></tbody></table></div>
   <h4>${tr('folderDetails')} (<span id="mrFolderCount">0</span>)</h4><div class="folder-table"><table><thead><tr><th>${tr('scope')}</th><th>${tr('folder')}</th><th>${tr('status')}</th><th>${tr('observed')}</th></tr></thead><tbody id="mrFolderRows"></tbody></table></div>
   <h4>${tr('events')}</h4><div class="log" id="mrRunEvents"></div>
   <div class="actions"><a class="btn small" href="/api/runs/${encodeURIComponent(runId)}/progress.csv" download>${tr('exportArea')}</a><a class="btn small" href="/api/runs/${encodeURIComponent(runId)}/folders.csv" download>${tr('exportFolders')}</a></div>
   <div id="mrRunErrors"></div></div>`;
  host.dataset.renderedRun=runId;
 }
 // Only change live values whose contents actually changed.
 function textIfChanged(id,value){const el=$(id);if(el.textContent!==String(value))el.textContent=String(value)}
 function htmlIfChanged(id,markup){const el=$(id);if(el.innerHTML!==markup){const top=el.closest('.folder-table,.log')?.scrollTop;el.innerHTML=markup;if(top!==undefined)el.closest('.folder-table,.log').scrollTop=top}}
 htmlIfChanged('mrRunStatus',tag(r.status));
 textIfChanged('mrRunPercent',`${pct}% ${tr('foldersProgress')}`);
 if($('mrRunBar').style.width!==`${pct}%`)$('mrRunBar').style.width=`${pct}%`;
 [[tr('files'),r.processed_files],[tr('included'),r.included_files],[tr('excluded'),r.excluded_files],[tr('folders'),`${done}/${total}`],['NEW',r.new_files],['CHANGED',r.changed_files],['UNCHANGED',r.unchanged_files],[tr('errors'),r.inaccessible]].forEach(([k,v],i)=>{
  const ln=host.querySelector(`[data-mr-label="${i}"]`),vn=host.querySelector(`[data-mr-val="${i}"]`);
  const value=typeof v==='number'?num(v):String(v);
  if(ln.textContent!==k)ln.textContent=k;
  if(vn.textContent!==value)vn.textContent=value;
 });
 const scopeMarkup=data.areas.map(a=>{
  let status=r.status==='PAUSED'?'PAUSED':r.status==='PAUSING'?'PAUSING':r.status==='CANCELLING'?'CANCELLING':r.status==='CANCELLED'?'CANCELLED':a.folders_failed?'ERROR':a.folders_pending?'IN PROGRESS':'DONE';
  return `<tr><td>${esc(a.label)}<div class="muted monospace">${esc(a.root)}</div></td><td>${num(a.folders_done)} / ${num(a.folders_total)}</td><td>${num(a.observed_files)}</td><td>${tag(status)}</td></tr>`;
 }).join('');
 htmlIfChanged('mrScopeRows',scopeMarkup);
 textIfChanged('mrFolderCount',num(folders.length));
 const folderMarkup=folders.slice(0,90).map(f=>`<tr><td>${num(f.scope_id)}</td><td class="monospace">${esc(f.relative||f.path)}</td><td>${tag(f.status)}</td><td>${num(f.file_count)}</td></tr>`).join('');
 htmlIfChanged('mrFolderRows',folderMarkup);
 textIfChanged('mrRunEvents',data.events.map(e=>`[${e.level}] ${time(e.recorded_at)} ${e.message}`).join('\n')||'—');
 htmlIfChanged('mrRunErrors',data.errors.length?`<h4>${tr('errors')}</h4><div class="log">${data.errors.map(e=>`${esc(e.path)} — ${esc(e.error)}`).join('\n')}</div>`:'');
}

async function renderFiles(){if(!state.wid)return;const q=$('fileQuery').value;const d=await api(`/api/workspaces/${state.wid}/files?q=${encodeURIComponent(q)}&limit=100&offset=${state.fileOffset}`);$('filesTable').innerHTML=d.files.length?d.files.map(f=>`<tr><td><b>${esc(f.filename)}</b></td><td>${esc(f.file_type)}</td><td>${tag(f.scope_decision)}</td><td>${tag(f.observation_status)}</td><td class="monospace">${esc(f.relative)}</td></tr>`).join(''):`<tr><td colspan="5">${tr('noFiles')}</td></tr>`;$('fileCount').textContent=`${num(d.offset+1)}–${num(Math.min(d.total,d.offset+d.files.length))} / ${num(d.total)}`;$('prevFiles').disabled=state.fileOffset===0;$('nextFiles').disabled=state.fileOffset+100>=d.total}
async function selectTab(tab){state.tab=tab;document.querySelectorAll('.tab-panel').forEach(n=>n.hidden=n.id!=='tab-'+tab);document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));if(tab==='progress')await loadDetail();if(tab==='files')await renderFiles()}
function showScope(id=null){state.scopeEditing=id;const form=$('scopeForm');form.reset();form.elements.recursive.checked=true;form.elements.enabled.checked=true;form.elements.max_depth.value='-1';form.elements.include.value='*';form.elements.exclude.value='~$*\n**/.git/**\n**/__pycache__/**';form.elements.override.value='';if(id){const s=state.detail.scopes.find(x=>x.id===id);for(const key of ['label','root','max_depth'])form.elements[key].value=s[key];for(const key of ['include','exclude','override'])form.elements[key].value=s[key].join('\n');form.elements.recursive.checked=!!s.recursive;form.elements.enabled.checked=!!s.enabled}$('scopeModal').showModal()}
async function changeLanguage(){state.lang=state.lang==='fa'?'en':'fa';localStorage.setItem('mr_lang',state.lang);translate();await loadWorkspaces();if(state.wid)await loadDetail()}
async function act(f){try{await f()}catch(e){toast(e.message,true)}}
$('newWorkspace').onclick=$('welcomeNew').onclick=()=>$('workspaceModal').showModal();
$('workspaceForm').onsubmit=e=>{e.preventDefault();act(async()=>{const f=e.target.elements;const r=await api('/api/workspaces','POST',{name:f.name.value,description:f.description.value});$('workspaceModal').close();await loadWorkspaces();await chooseWorkspace(r.id);await selectTab('scope')})};
$('addScope').onclick=()=>showScope();$('scopeForm').onsubmit=e=>{e.preventDefault();act(async()=>{const f=e.target.elements;const body={label:f.label.value,root:f.root.value,recursive:f.recursive.checked,enabled:f.enabled.checked,max_depth:Number(f.max_depth.value),include:f.include.value,exclude:f.exclude.value,override:f.override.value};await api(state.scopeEditing?`/api/workspaces/${state.wid}/scopes/${state.scopeEditing}`:`/api/workspaces/${state.wid}/scopes`,'POST',body);$('scopeModal').close();await loadDetail()})};document.querySelectorAll('.closeModal').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('refresh').onclick=()=>act(async()=>{await loadWorkspaces();await loadDetail()});$('language').onclick=()=>act(changeLanguage);document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>act(()=>selectTab(b.dataset.tab)));
$('startScan').onclick=()=>act(async()=>{let r=await api(`/api/workspaces/${state.wid}/runs`,'POST',{budget:Number($('budget').value)||0});state.runId=r.id;await selectTab('progress');await loadDetail()});
$('resumeScan').onclick=()=>act(async()=>{await api(`/api/runs/${state.runId}/resume`,'POST',{budget:Number($('budget').value)||0});await loadDetail()});
$('pauseScan').onclick=()=>act(async()=>{await api(`/api/runs/${state.runId}/pause`,'POST',{});await loadDetail()});
$('cancelScan').onclick=()=>act(async()=>{if(!confirm(tr('confirmCancel')))return;await api(`/api/runs/${state.runId}/cancel`,'POST',{});await loadDetail()});
$('searchFiles').onclick=()=>act(async()=>{state.fileOffset=0;await renderFiles()});$('fileQuery').onkeydown=e=>{if(e.key==='Enter')$('searchFiles').click()};$('prevFiles').onclick=()=>act(async()=>{state.fileOffset=Math.max(0,state.fileOffset-100);await renderFiles()});$('nextFiles').onclick=()=>act(async()=>{state.fileOffset+=100;await renderFiles()});
translate();loadWorkspaces().catch(e=>toast(e.message,true));setInterval(()=>{if(!state.wid||state.tab!=='progress'||!state.runId||state.pollPending)return;state.pollPending=true;loadDetail(true).catch(()=>{}).finally(()=>{state.pollPending=false})},2400);
