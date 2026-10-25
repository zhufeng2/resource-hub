'use strict';
const $ = (id) => document.getElementById(id);
const clouds = {quark:'夸克',baidu:'百度',aliyun:'阿里',guangya:'光鸭',tianyi:'天翼','115':'115',xunlei:'迅雷',uc:'UC',mobile:'移动',pikpak:'PikPak','123':'123',magnet:'磁力',ed2k:'电驴',others:'其他'};
const sources = {qqpd:'QQ 频道',gying:'观影',panlian:'盘链',weibo:'微博',woniu:'蜗牛'};
const defaults = {cloud_types:['quark'],channels:[],plugins:[],src:'all',page_size:20,view:'list',sort:'relevance',theme:'light',auto_check:false,hide_invalid:false};
let state = {user:null,csrf:'',prefs:{...defaults},catalog:{plugins:[],channels:[]},rows:[],search:null,page:0,checks:new Map(),busy:false,tab:'profile'};
let toastTimer, pollTimer, modalCleanup;

function node(tag, attrs={}, children=[]) {
  const element = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key==='text') element.textContent=value;
    else if (key==='class') element.className=value;
    else if (key.startsWith('on')) element.addEventListener(key.slice(2),value);
    else if (key==='checked' || key==='disabled') element[key]=value;
    else if (value!==null && value!==undefined) element.setAttribute(key,value);
  }
  for (const child of Array.isArray(children)?children:[children]) element.append(child);
  return element;
}
function toast(message) {
  $('toast').textContent=message; $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,3500);
}
function message(error) { return error instanceof Error ? error.message : String(error); }
async function api(path, options={}) {
  const headers = {'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...options.headers};
  if (options.method && options.method!=='GET') headers['X-CSRF-Token']=state.csrf;
  const response=await fetch(path,{credentials:'same-origin',...options,headers});
  let data; try { data=await response.json(); } catch { throw new Error('服务暂时不可用，请稍后重试。'); }
  if (data.quota && state.user) {state.user.quota=data.quota; renderQuota();}
  if (!response.ok || data.error) {
    if (response.status===401 && path!=='/api/login') await boot();
    throw new Error(data.message || data.error || '操作未完成，请稍后重试。');
  }
  return data;
}
const post=(path,data={})=>api(path,{method:'POST',body:JSON.stringify(data)});
async function clipboard(text) {
  try { await navigator.clipboard.writeText(text); toast('已复制'); }
  catch { toast('浏览器未允许复制，请手动选择链接。'); }
}
function requestId() { return crypto.randomUUID(); }
function safeUrl(value) {
  try { const parsed=new URL(value); return ['https:','http:','magnet:','ed2k:'].includes(parsed.protocol)?value:null; }
  catch { return null; }
}
function theme(value) {
  document.documentElement.dataset.theme=value==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):value;
}
function renderQuota() {
  const q=state.user?.quota; if(!q)return;
  $('quota-small').replaceChildren('今日剩余 ',node('strong',{text:q.remaining}),' / '+q.daily_limit);
  $('quota-remaining').textContent=q.remaining; $('quota-total').textContent='/ '+q.daily_limit+' 次';
  const count=Math.max(1,Math.min(q.daily_limit,10));
  $('quota-meter').replaceChildren(...Array.from({length:count},(_,i)=>node('i',{class:i<Math.ceil(q.remaining/Math.max(1,q.daily_limit)*count)?'available':''})));
  $('profile-used').textContent=q.used; $('profile-remaining').textContent=q.remaining; $('profile-limit').textContent=q.daily_limit;
}
function navigate() {
  const route=location.hash.slice(1).split('?')[0] || 'search';
  const current=['search','settings','account'].includes(route)?route:'search';
  document.querySelectorAll('[data-page]').forEach(p=>p.hidden=p.dataset.page!==current);
  document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===current)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.title=({search:'搜索',settings:'配置',account:'账号'}[current])+' · Resource Hub';
  if(!state.user)return;
  if(current==='settings'){renderSettings();loadCatalog();}
  if(current==='account')accountTab(state.tab);
}
async function boot() {
  try {
    const data=await api('/api/session'); state.csrf=data.csrf;
    const signedIn=!!data.username;
    $('login-view').hidden=signedIn; $('workspace').hidden=!signedIn;
    $('navigation').hidden=!signedIn; $('header-account').hidden=!signedIn;
    if(!signedIn){state.user=null;state.rows=[];return;}
    state.user=data; state.prefs={...defaults,...data.preferences}; theme(state.prefs.theme);
    $('avatar').textContent=data.username[0].toUpperCase(); $('profile-avatar').textContent=data.username[0].toUpperCase();
    $('profile-name').textContent=data.username; $('profile-role').textContent=data.is_admin?'管理员':'成员';
    $('users-tab').hidden=!data.is_admin; $('mcp-url').textContent=data.mcp_url;
    if(data.preview){$('footer-note').textContent='界面预览 · 示例数据';$('footer-note').classList.add('preview-label');}
    renderQuota(); renderSearchClouds(); navigate(); loadHistory();
  } catch(error) { $('login-view').hidden=false; $('login-error').textContent=message(error); }
}
$('login-form').addEventListener('submit',async(event)=>{
  event.preventDefault(); const form=event.currentTarget; const button=form.querySelector('button');button.disabled=true;
  $('login-error').textContent='';
  try {await post('/api/login',Object.fromEntries(new FormData(form)));form.reset();await boot();}
  catch(error){$('login-error').textContent=message(error);}
  finally {button.disabled=false;}
});
window.addEventListener('hashchange',navigate);
window.addEventListener('keydown',event=>{
  if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)&&!$('modal').open&&state.user){event.preventDefault();location.hash='search';$('query').focus();}
});
function renderSearchClouds() {
  const options=[['all','全部'],['quark','夸克'],['baidu','百度'],['aliyun','阿里'],['more','更多']];
  const selected=state.prefs.cloud_types;
  $('search-clouds').replaceChildren(...options.map(([value,label])=>node('button',{
    class:'chip',type:'button','aria-pressed':String(value==='all'?selected.length===0:value==='more'?selected.some(x=>!['quark','baidu','aliyun'].includes(x)):selected.includes(value)),
    text:label,onclick:()=>{
      if(value==='more'){location.hash='settings';return;}
      state.prefs.cloud_types=value==='all'?[]:[value];renderSearchClouds();
    }
  })));
}
async function loadHistory() {
  try {
    const {items}=await api('/api/history');
    $('recent-searches').replaceChildren(...(items.length?items.map(item=>node('button',{class:'recent-row',onclick:()=>loadResult(item.id)},[
      node('span',{text:item.query}),node('small',{text:new Date(item.created*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})})
    ])):[node('p',{class:'muted small',text:'暂无搜索记录'})]));
  } catch { /* Login state handles authentication failures. */ }
}
function searchStatus(text,loading=false) {
  $('search-status').hidden=false;
  $('search-status').replaceChildren(...(loading?[node('span',{class:'spinner','aria-hidden':'true'}),document.createTextNode(text)]:[document.createTextNode(text)]));
}
async function loadResult(id) {
  try { const data=await api('/api/results/'+encodeURIComponent(id)); setResults(data);location.hash='search'; }
  catch(error){toast(message(error));}
}
function setResults(data) {
  state.search=data;state.rows=data.results||[];state.page=0;state.checks.clear();
  $('query').value=data.query||''; $('empty-state').hidden=true;$('search-status').hidden=true;
  $('result-toolbar').hidden=false; $('result-note').hidden=false;
  $('sort-results').value=state.prefs.sort; renderResults();
}
async function runSearch(query,path='/api/search',extra={}) {
  if(state.busy || !query.trim())return;
  state.busy=true;const start=performance.now();$('search-button').disabled=true;$('search-button').textContent='搜索中…';
  $('results-area').setAttribute('aria-busy','true');$('empty-state').hidden=true;$('result-toolbar').hidden=true;
  $('results').replaceChildren();$('pagination').hidden=true;$('result-note').hidden=true;
  searchStatus('正在搜索，请稍候…',true);
  try {
    const payload=path==='/api/search'?{query,request_id:requestId(),options:state.prefs,...extra}:{action:'test_search',keyword:query,request_id:requestId(),...extra};
    let data=await post(path,payload);
    if(data.available_count>data.results.length)data=await api('/api/results/'+encodeURIComponent(data.search_id));
    data.elapsed=((performance.now()-start)/1000).toFixed(1);setResults(data);loadHistory();
  } catch(error) {state.rows=[];state.search=null;searchStatus(message(error));}
  finally {state.busy=false;$('search-button').disabled=false;$('search-button').replaceChildren('搜索 ',node('span',{'aria-hidden':'true',text:'↗'}));$('results-area').setAttribute('aria-busy','false');}
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();runSearch($('query').value);});
$('refresh-results').addEventListener('click',()=>{if(state.search)runSearch(state.search.query,'/api/search',{refresh:true});});
$('advanced-toggle').addEventListener('click',()=>{const hidden=!$('advanced-filters').hidden;$('advanced-filters').hidden=hidden;$('advanced-toggle').setAttribute('aria-expanded',String(!hidden));});
const words=value=>value.trim().toLowerCase().split(/[\s,，]+/).filter(Boolean);
function filteredRows() {
  const include=words($('include-words').value),exclude=words($('exclude-words').value);
  const rows=state.rows.filter(row=>{
    const text=(row.title+' '+row.source).toLowerCase();
    return (!include.length||include.some(w=>text.includes(w)))&&!exclude.some(w=>text.includes(w))&&!(state.prefs.hide_invalid&&state.checks.get(row.url)?.state==='bad');
  });
  if($('sort-results').value==='newest')rows.sort((a,b)=>(Date.parse(b.datetime)||0)-(Date.parse(a.datetime)||0));
  return rows;
}
function highlighted(text,query) {
  const fragment=document.createDocumentFragment();const index=text.toLowerCase().indexOf(query.toLowerCase());
  if(index<0||!query){fragment.append(text);return fragment;}
  fragment.append(text.slice(0,index),node('mark',{text:text.slice(index,index+query.length)}),text.slice(index+query.length));return fragment;
}
function renderResults() {
  if(!state.search)return;
  const rows=filteredRows(),size=state.prefs.page_size,total=Math.max(1,Math.ceil(rows.length/size));
  state.page=Math.min(state.page,total-1);const visible=rows.slice(state.page*size,(state.page+1)*size);
  $('results').className='result-list'+(state.prefs.view==='grid'?' grid':'');
  $('result-title').textContent='搜索结果';$('result-count').textContent=rows.length+' 条'+(state.search.elapsed?' · '+state.search.elapsed+' 秒':'');
  $('results').replaceChildren(...visible.map(row=>{
    const url=safeUrl(row.url), title=node(url?'a':'span',{class:'result-title',...(url?{href:url,target:'_blank',rel:'noopener noreferrer'}:{})},[highlighted(row.title||'未命名资源',state.search.query)]);
    const metadata=[node('span',{class:'disk-label',text:clouds[row.cloud_type]||row.cloud_type})];
    if(row.source)metadata.push(node('span',{text:row.source.replace(/^plugin:/,'')}));
    if(row.datetime)metadata.push(node('span',{text:row.datetime.slice(0,10)}));
    if(row.password)metadata.push(node('button',{class:'text-button',text:'提取码 '+row.password,onclick:()=>clipboard(row.password)}));
    const check=state.checks.get(row.url);
    metadata.push(node('button',{class:'text-button check-state '+(check?.state||''),text:check?({ok:'有效',good:'有效',bad:'已失效',unknown:'未确定'}[check.state]||'未确定'):'检测链接',title:check?.summary||'检查分享链接状态',onclick:()=>checkVisible([row])}));
    return node('article',{class:'result-row'},[node('div',{class:'disk-icon','aria-hidden':'true',text:(clouds[row.cloud_type]||'资源').slice(0,2)}),node('div',{class:'result-main'},[title,node('div',{class:'result-meta'},metadata)]),node('div',{class:'result-actions'},[
      node('button',{class:'text-button',text:'复制链接',onclick:()=>clipboard(row.url+(row.password?'\n提取码：'+row.password:''))}),
      ...(url?[node('a',{class:'open-link',href:url,target:'_blank',rel:'noopener noreferrer',text:'↗','aria-label':'打开 '+row.title})]:[])
    ])]);
  }));
  if(!visible.length)$('results').append(node('p',{class:'no-results',text:state.rows.length?'没有符合筛选条件的结果。':'没有找到相关资源，试试更短的关键词。'}));
  $('pagination').hidden=total<=1;
  $('pagination').replaceChildren(node('button',{text:'← 上一页',disabled:state.page===0,onclick:()=>{state.page--;renderResults();}}),node('span',{text:(state.page+1)+' / '+total}),node('button',{text:'下一页 →',disabled:state.page===total-1,onclick:()=>{state.page++;renderResults();}}));
  if(state.prefs.auto_check){const pending=visible.filter(r=>!state.checks.has(r.url)).slice(0,20);if(pending.length)checkVisible(pending,true);}
}
async function checkVisible(rows,automatic=false) {
  rows=rows.filter(r=>r.url.startsWith('http')).slice(0,20);if(!rows.length)return;
  rows.forEach(r=>state.checks.set(r.url,{state:'checking'}));
  try {const data=await post('/api/check',{search_id:state.search.search_id,urls:rows.map(r=>r.url)});rows.forEach((r,i)=>state.checks.set(r.url,data.results[i]));renderResults();}
  catch(error){rows.forEach(r=>state.checks.set(r.url,{state:'unknown',summary:message(error)}));if(!automatic)toast(message(error));renderResults();}
}
['include-words','exclude-words'].forEach(id=>$(id).addEventListener('input',()=>{state.page=0;renderResults();}));
$('sort-results').addEventListener('change',()=>{state.page=0;renderResults();});
$('view-toggle').addEventListener('click',()=>{state.prefs.view=state.prefs.view==='list'?'grid':'list';renderResults();});
function download(filename,data,type='application/json') {
  const url=URL.createObjectURL(new Blob([data],{type}));const a=node('a',{href:url,download:filename});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function openModal(title,content) {
  clearInterval(pollTimer);if(modalCleanup)modalCleanup();modalCleanup=null;
  $('modal-title').textContent=title;$('modal-body').replaceChildren(content);if(!$('modal').open)$('modal').showModal();
}
function closeModal(){clearInterval(pollTimer);if(modalCleanup)modalCleanup();modalCleanup=null;$('modal').close();}
$('close-modal').addEventListener('click',closeModal);
$('modal').addEventListener('close',()=>{clearInterval(pollTimer);if(modalCleanup)modalCleanup();modalCleanup=null;});
$('export-button').addEventListener('click',()=>{
  const form=node('form');form.append(node('p',{class:'muted small',text:'导出当前筛选结果，共 '+filteredRows().length+' 条。'}));
  const select=node('select',{name:'format'},[['txt','文本 TXT'],['csv','表格 CSV'],['json','JSON']].map(([value,text])=>node('option',{value,text})));
  form.append(field('文件格式',select),node('div',{class:'form-actions'},[node('button',{class:'primary',type:'submit',text:'下载结果 ↓'})]));
  form.addEventListener('submit',event=>{event.preventDefault();const rows=filteredRows(),format=select.value;let output;
    if(format==='json')output=JSON.stringify(rows,null,2);
    else if(format==='csv'){const quote=value=>{let text=String(value??'');if(/^[\s]*[=+@-]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};output='\ufeff'+['名称,网盘,链接,提取码,来源,日期',...rows.map(r=>[r.title,clouds[r.cloud_type]||r.cloud_type,r.url,r.password,r.source,r.datetime].map(quote).join(','))].join('\r\n');}
    else output=rows.map(r=>r.title+'\n'+r.url+(r.password?'\n提取码：'+r.password:'')).join('\n\n');
    download('搜索结果.'+format,output,format==='json'?'application/json':'text/plain;charset=utf-8');closeModal();
  });openModal('导出结果',form);
});
function field(label,input){return node('label',{text:label},[input]);}
function splitNames(value){return [...new Set(value.split(/[\s,，]+/).map(v=>v.trim()).filter(Boolean))];}
function renderSettings() {
  const p=state.prefs;
  $('settings-clouds').replaceChildren(...Object.entries(clouds).filter(([id])=>id!=='others').map(([id,label])=>node('label',{class:'choice-item'},[node('input',{type:'checkbox',value:id,checked:p.cloud_types.includes(id)}),document.createTextNode(label)])));
  $('source-mode').value=p.src;$('plugin-input').value=p.plugins.join(', ');$('channel-input').value=p.channels.join('\n');
  $('page-size').value=p.page_size;$('default-view').value=p.view;$('default-sort').value=p.sort;$('theme').value=p.theme;
  $('auto-check').checked=p.auto_check;$('hide-invalid').checked=p.hide_invalid;
  renderCatalog();
}
function collectSettings(){return {cloud_types:[...$('settings-clouds').querySelectorAll('input:checked')].map(x=>x.value),plugins:splitNames($('plugin-input').value),channels:splitNames($('channel-input').value),src:$('source-mode').value,page_size:Number($('page-size').value),view:$('default-view').value,sort:$('default-sort').value,theme:$('theme').value,auto_check:$('auto-check').checked,hide_invalid:$('hide-invalid').checked};}
async function loadCatalog() {
  $('catalog-status').textContent='正在读取搜索源…';
  try {state.catalog=await api('/api/catalog');$('catalog-status').textContent='已读取可用搜索源。';renderCatalog();}
  catch(error){$('catalog-status').textContent=message(error)+' 可手动填写名称。';}
}
function renderCatalog(){
  for(const [key,inputId,target,count] of [['plugins','plugin-input','plugin-choices','plugin-count'],['channels','channel-input','channel-choices','channel-count']]){
    const values=state.catalog[key]||[];$(count).textContent=values.length+' 项';
    $(target).replaceChildren(...values.map(value=>node('button',{class:'chip',type:'button',text:value,'aria-pressed':String(splitNames($(inputId).value).includes(value)),onclick:()=>{const set=new Set(splitNames($(inputId).value));set.has(value)?set.delete(value):set.add(value);$(inputId).value=[...set].join(', ');renderCatalog();}})));
  }
}
$('reload-catalog').addEventListener('click',loadCatalog);
$('select-all-clouds').addEventListener('click',()=>{const inputs=[...$('settings-clouds').querySelectorAll('input')];const checked=!inputs.every(x=>x.checked);inputs.forEach(x=>x.checked=checked);});
$('save-settings').addEventListener('click',async()=>{const button=$('save-settings');button.disabled=true;try{state.prefs=await api('/api/preferences',{method:'PUT',body:JSON.stringify(collectSettings())});theme(state.prefs.theme);renderSearchClouds();toast('配置已保存');}catch(error){toast(message(error));}finally{button.disabled=false;}});
$('reset-settings').addEventListener('click',()=>{state.prefs={...defaults};renderSettings();theme('light');toast('已恢复默认选项，保存后生效');});
$('theme').addEventListener('change',()=>theme($('theme').value));
$('export-config').addEventListener('click',()=>download('resource-hub-settings.json',JSON.stringify(collectSettings(),null,2)));
$('import-config').addEventListener('change',async(event)=>{const file=event.target.files[0];if(!file)return;try{if(file.size>10000)throw new Error();const data=JSON.parse(await file.text());if(!Array.isArray(data.cloud_types)||!Array.isArray(data.plugins)||!Array.isArray(data.channels))throw new Error();state.prefs={...defaults,...data};renderSettings();toast('配置已载入，保存后生效');}catch{toast('配置文件格式不正确。');}event.target.value='';});
document.querySelectorAll('[data-scroll]').forEach(a=>a.addEventListener('click',event=>{event.preventDefault();$(a.dataset.scroll).scrollIntoView({behavior:'smooth',block:'start'});}));
async function accountTab(tab){
  if(tab==='users'&&!state.user?.is_admin)tab='profile';state.tab=tab;
  document.querySelectorAll('[data-account-panel]').forEach(p=>p.hidden=p.dataset.accountPanel!==tab);
  document.querySelectorAll('[data-account-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.accountTab===tab)));
  if(tab==='sources')loadBindings();if(tab==='users')loadUsers();
}
document.querySelectorAll('[data-account-tab]').forEach(b=>b.addEventListener('click',()=>accountTab(b.dataset.accountTab)));
$('logout-button').addEventListener('click',async()=>{try{await post('/api/logout');await boot();}catch(error){toast(message(error));}});
$('password-form').addEventListener('submit',async(event)=>{event.preventDefault();const form=event.currentTarget,data=Object.fromEntries(new FormData(form));if(data.password!==data.confirm){toast('两次输入的密码不一致。');return;}try{await post('/api/password',data);form.reset();toast('密码已更新，请重新登录');await boot();}catch(error){toast(message(error));}});
$('copy-mcp').addEventListener('click',()=>clipboard(state.user.mcp_url));
$('revoke-connections').addEventListener('click',()=>{
  const body=node('div',{},[node('p',{class:'muted small',text:'撤销后，已连接的 ChatGPT 需要重新登录。'}),node('div',{class:'form-actions'},[node('button',{class:'secondary',text:'取消',onclick:closeModal}),node('button',{class:'primary',text:'撤销授权',onclick:async()=>{try{await post('/api/connections/revoke');closeModal();toast('已撤销授权');}catch(error){toast(message(error));}}})])]);openModal('撤销 ChatGPT 授权',body);
});
async function loadUsers(){try{const data=await api('/api/users');$('users-table').replaceChildren(...data.items.map(user=>node('tr',{},[node('td',{text:user.username}),node('td',{text:user.is_admin?'管理员':'成员'}),node('td',{text:user.daily_limit+' 次'}),node('td',{},[node('span',{class:'pill',text:user.enabled?'正常':'已停用'})]),node('td',{},[node('button',{class:'text-button',text:'编辑 ↗',onclick:()=>userEditor(user)})])])));}catch(error){toast(message(error));}}
function userEditor(user=null){
  const form=node('form'),username=node('input',{name:'username',maxlength:'64',required:'',value:user?.username||'',...(user?{readonly:''}:{})}),password=node('input',{name:'password',type:'password',minlength:'12',maxlength:'256',autocomplete:'new-password',...(!user?{required:''}:{placeholder:'留空保留当前密码'})}),limit=node('input',{name:'daily_limit',type:'number',min:'0',max:'10000',value:user?.daily_limit??5,required:''}),admin=node('input',{name:'is_admin',type:'checkbox',checked:!!user?.is_admin}),enabled=node('input',{name:'enabled',type:'checkbox',checked:user?!!user.enabled:true});
  form.append(field('账号',username),field(user?'重置密码':'密码',password),field('每日搜索额度',limit),node('label',{class:'toggle-row'},[node('span',{text:'管理员权限'}),admin]));if(user)form.append(node('label',{class:'toggle-row'},[node('span',{text:'启用账号'}),enabled]));
  form.append(node('div',{class:'form-actions'},[node('button',{type:'button',class:'secondary',text:'取消',onclick:closeModal}),node('button',{type:'submit',class:'primary',text:user?'保存修改':'创建用户'})]));
  form.addEventListener('submit',async(event)=>{event.preventDefault();try{await api('/api/users',{method:user?'PATCH':'POST',body:JSON.stringify({username:username.value,password:password.value,daily_limit:Number(limit.value),is_admin:admin.checked,enabled:enabled.checked})});closeModal();loadUsers();toast(user?'账号已更新':'账号已创建');}catch(error){toast(message(error));}});openModal(user?'编辑账号':'创建用户',form);
}
$('add-user').addEventListener('click',()=>userEditor());
async function loadBindings(){try{const {items}=await api('/api/bindings');$('bindings').replaceChildren(...items.map(item=>node('article',{class:'binding-card'},[node('div',{class:'disk-icon',text:sources[item.provider].slice(0,2)}),node('h3',{text:item.label}),node('p',{text:sources[item.provider]}),node('div',{class:'binding-bottom'},[node('span',{class:'small-label',text:'账号连接'}),node('button',{class:'text-button',text:'管理 ↗',onclick:()=>bindingEditor(item)})])])));if(!items.length)$('bindings').append(node('p',{class:'muted small',text:'还没有添加搜索源账号。'}));}catch(error){toast(message(error));}}
$('add-binding').addEventListener('click',async()=>{
  await loadCatalog();const form=node('form'),select=node('select',{required:''},Object.entries(sources).filter(([id])=>state.catalog.plugins.includes(id)).map(([id,name])=>node('option',{value:id,text:name}))),label=node('input',{maxlength:'64',required:'',placeholder:'例如：我的观影账号'});
  form.append(field('搜索源',select),field('账号名称',label));if(!select.options.length)form.append(node('p',{class:'field-help',text:'当前没有启用需要绑定账号的搜索源。'}));
  form.append(node('div',{class:'form-actions'},[node('button',{class:'primary',type:'submit',text:'继续',disabled:!select.options.length})]));
  form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const data=await post('/api/bindings',{provider:select.value,label:label.value});loadBindings();const binding=data.items[data.items.length-1];bindingEditor(binding);}catch(error){toast(message(error));}finally{button.disabled=false;}});openModal('添加搜索源账号',form);
});
async function bindingEditor(binding){
  const body=node('div'),status=node('p',{class:'source-status',text:'正在读取账号状态…'}),area=node('div'),actions=node('div',{class:'source-actions'});
  body.append(status,area,actions);openModal(binding.label+' · '+sources[binding.provider],body);
  let active=true,captchaId='',confirmId='';modalCleanup=()=>{active=false;body.querySelectorAll('input[type=password]').forEach(x=>x.value='');};
  const call=(action,data={})=>post('/api/bindings/'+encodeURIComponent(binding.id),{action,...data});
  const statusText=data=>data.logged_in?'已连接'+(data.username?' · '+data.username:''):data.login_status==='waiting'?'请使用对应 App 扫码登录':data.login_status==='expired'?'二维码已过期，请刷新':'尚未登录';
  const qr=data=>{const raw=data.qrcode_base64||data.image;if(!raw)return null;const src=raw.startsWith('data:image/')?raw:'data:image/png;base64,'+raw;return /^data:image\/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\s]+$/.test(src)?node('img',{class:'qr-image',src,alt:binding.provider==='panlian'?'登录验证码':'扫码登录二维码'}):null;};
  async function refresh(){try{const response=await call('get_status');if(!active)return;status.textContent=statusText(response.data);show(response.data);}catch(error){status.textContent=message(error);}}
  function show(data){
    area.replaceChildren();actions.replaceChildren();
    if(['qqpd','weibo'].includes(binding.provider)){
      const image=qr(data);if(image)area.append(image);
      if(!data.logged_in){
        actions.append(node('button',{class:'secondary',text:'刷新二维码',onclick:async()=>{try{const response=await call('refresh_qrcode');if(!active)return;const image=qr(response.data);area.replaceChildren(...(image?[image]:[]));status.textContent='请使用对应 App 扫码登录';startPoll();}catch(error){toast(message(error));}}}));
        if(image)startPoll();
      }else{
        const key=binding.provider==='qqpd'?'channels':'user_ids';const input=node('textarea',{rows:'3',placeholder:'多个名称或 ID 用逗号或换行分隔'});input.value=(data[key]||[]).join('\n');area.append(field(key==='channels'?'搜索频道':'微博用户 ID',input),node('button',{class:'secondary',text:'保存范围',onclick:async()=>{try{const response=await call(key==='channels'?'set_channels':'set_user_ids',{[key]:splitNames(input.value)});toast(response.success?'已保存':response.message||'保存失败');}catch(error){toast(message(error));}}}));
      }
    }else if(!data.logged_in){
      const form=node('form'),username=node('input',{required:'',maxlength:'128',autocomplete:'username'}),password=node('input',{type:'password',required:'',maxlength:'256',autocomplete:'current-password'}),captcha=node('input',{maxlength:'20',placeholder:'输入图形验证码'}),email=node('input',{type:'email',maxlength:'254',placeholder:'输入账号绑定的邮箱'}),captchaArea=node('div');
      form.append(field('搜索源账号',username),field('密码',password));
      async function reloadCaptcha(){try{const response=await call('captcha');if(!active)return;captchaId=response.data.captcha_id||'';const image=qr(response.data);captchaArea.replaceChildren(...(image?[image]:[]),field('验证码',captcha),node('button',{type:'button',class:'text-button',text:'换一张',onclick:reloadCaptcha}));}catch(error){toast(message(error));}}
      if(binding.provider==='panlian'){form.append(captchaArea);reloadCaptcha();}
      const emailField=field('确认邮箱',email);emailField.hidden=true;form.append(emailField);
      form.append(node('button',{type:'submit',class:'primary full',text:'登录搜索源'}));
      form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('button[type=submit]');button.disabled=true;try{const response=await call(confirmId?'confirm_email':'login',{username:username.value,password:password.value,captcha_id:captchaId,captcha_code:captcha.value,confirm_id:confirmId,email:email.value});if(!active)return;if(response.data.need_email){confirmId=response.data.confirm_id;emailField.hidden=false;email.required=true;status.textContent=response.data.email_hint||'请确认账号绑定的邮箱。';}else if(response.success){password.value='';await refresh();toast('账号已连接');}else{toast(response.message||'登录未完成');if(binding.provider==='panlian')reloadCaptcha();}}catch(error){toast(message(error));}finally{button.disabled=false;}});area.append(form);
    }
    if(data.logged_in){
      const input=node('input',{maxlength:'120',required:'',placeholder:'输入关键词测试搜索'}),form=node('form');form.append(node('div',{class:'divider'}),field('测试搜索',input),node('p',{class:'field-help',text:'成功搜索将使用 1 次额度。'}),node('button',{class:'secondary',type:'submit',text:'搜索'}));form.addEventListener('submit',event=>{event.preventDefault();const query=input.value;closeModal();location.hash='search';runSearch(query,'/api/bindings/'+encodeURIComponent(binding.id));});area.append(form);
      actions.append(node('button',{class:'text-button',text:'退出搜索源账号',onclick:async()=>{try{const response=await call('logout');if(response.success)refresh();else toast(response.message||'退出失败');}catch(error){toast(message(error));}}}));
    }
    if(['gying','woniu'].includes(binding.provider))actions.append(node('button',{class:'text-button',text:'站点配置',onclick:async()=>{try{const response=await call('get_config');if(!active)return;const input=node('input',{type:'url',value:response.data.base_url||'',readonly:!state.user.is_admin?'':null});area.append(node('div',{class:'divider'}),field('站点地址',input));if(state.user.is_admin)area.append(node('button',{class:'secondary',text:'保存地址',onclick:async()=>{try{const saved=await call('update_config',{base_url:input.value});toast(saved.success?'站点地址已保存':saved.message||'保存失败');}catch(error){toast(message(error));}}}));}catch(error){toast(message(error));}}}));
    actions.append(node('button',{class:'text-button',text:'刷新状态',onclick:refresh}),node('button',{class:'text-button danger-text',text:'移除账号',onclick:async()=>{try{await call('remove');closeModal();loadBindings();toast('账号已移除');}catch(error){toast(message(error));}}}));
  }
  function startPoll(){clearInterval(pollTimer);let attempts=0;pollTimer=setInterval(async()=>{if(!active||++attempts>24){clearInterval(pollTimer);return;}try{const response=await call('check_login');if(!active)return;status.textContent=statusText(response.data);if(response.data.login_status==='success'){clearInterval(pollTimer);refresh();}else if(response.data.login_status==='expired'){clearInterval(pollTimer);}}catch{clearInterval(pollTimer);}},5000);}
  await refresh();
}
boot();
