'use strict';
const $=id=>document.getElementById(id);
const clouds={quark:'夸克',baidu:'百度',aliyun:'阿里',tianyi:'天翼','115':'115','123':'123',uc:'UC',mobile:'移动',guangya:'光鸭',xunlei:'迅雷',pikpak:'PikPak',magnet:'磁力',ed2k:'电驴',others:'其他'};
const sources={qqpd:'QQ 频道',gying:'观影',panlian:'盘链',weibo:'微博',woniu:'蜗牛'};
const defaults={cloud_types:['quark'],channels:[],plugins:[],src:'all',page_size:20,sort:'relevance',theme:'light',auto_check:true,hide_invalid:true,include_words:'',exclude_words:'',match_mode:'any'};
const initialTheme=window.ResourceTheme?.preference||defaults.theme;
let state={user:null,csrf:'',prefs:{...defaults,theme:initialTheme},savedPrefs:{...defaults,theme:initialTheme},catalog:{plugins:[],channels:[]},rows:[],search:null,page:0,checks:new Map(),busy:false,tab:'history',cache:new Map(),history:[],job:null,epoch:0,checking:false};
document.body.classList.toggle('has-results',document.documentElement.dataset.initialView==='results');
if(document.documentElement.dataset.initialView==='profile')$('home-view').hidden=true;
delete document.documentElement.dataset.initialView;
let pollTimer,modalCleanup,toastTimer,pendingJob,pendingAction,searchController,waitingTimer;
const clone=value=>JSON.parse(JSON.stringify(value));
class ApiError extends Error{constructor(data,status){super(data.message||data.error||'操作未完成，请重试');this.code=data.error;this.status=status;}}
function node(tag,attrs={},children=[]){const element=document.createElement(tag);for(const[key,value]of Object.entries(attrs)){if(key==='text')element.textContent=value;else if(key==='class')element.className=value;else if(key.startsWith('on'))element.addEventListener(key.slice(2),value);else if(key==='checked'||key==='disabled')element[key]=value;else if(value!==null&&value!==undefined)element.setAttribute(key,value);}for(const child of Array.isArray(children)?children:[children])element.append(child);return element;}
function message(error){return error instanceof TypeError?'网络连接失败，请检查网络后重试':error.message||String(error);}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
async function api(path,options={}){const headers={Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...options.headers};if(options.method&&options.method!=='GET')headers['X-CSRF-Token']=state.csrf;const response=await fetch(path,{credentials:'same-origin',...options,headers});let data;try{data=await response.json();}catch{throw new Error('服务暂时无法响应，请稍后重试');}if(data.quota&&state.user){state.user.quota=data.quota;renderQuota();}if(!response.ok||data.error)throw new ApiError(data,response.status);return data;}
const post=(path,data={},options={})=>api(path,{method:'POST',body:JSON.stringify(data),...options});
function requestId(){return crypto.randomUUID();}
async function clipboard(text){try{await navigator.clipboard.writeText(text);toast('已复制');}catch{toast('未能复制，请手动选择链接');}}
function safeUrl(value){try{return ['https:','http:','magnet:','ed2k:'].includes(new URL(value).protocol)?value:null;}catch{return null;}}
function field(label,input){return node('label',{text:label},[input]);}
function splitNames(value){return [...new Set(value.split(/[\s,，]+/).map(s=>s.trim()).filter(Boolean))];}
const words=value=>splitNames(value.toLowerCase());
function theme(value){window.ResourceTheme.apply(value);}
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{if(state.prefs.theme==='system')theme('system');});
function setMenu(open,focus=false){const menu=$('user-menu');menu.classList.toggle('open',open);menu.inert=!open;menu.setAttribute('aria-hidden',String(!open));$('avatar').setAttribute('aria-expanded',String(open));if(open&&focus)menu.querySelector('[role=menuitem]').focus();}
$('avatar').addEventListener('click',()=>setMenu($('user-menu').inert));
$('avatar').addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();setMenu(true,true);}});
$('user-menu').addEventListener('keydown',event=>{const items=[...$('user-menu').querySelectorAll('[role^=menuitem]')].filter(item=>!item.hidden&&!item.closest('[hidden]'));let index=items.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();index=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(['ArrowDown','ArrowRight'].includes(event.key)?1:-1)+items.length)%items.length;items[index].focus();}});
window.addEventListener('click',event=>{if(!$('user-control').contains(event.target)&&!$('user-menu').contains(event.target))setMenu(false);});
window.addEventListener('keydown',event=>{if(event.key==='Escape'){setMenu(false);if(!document.querySelector('dialog[open]')&&$('settings-toggle').getAttribute('aria-expanded')==='true')toggleSettings(false);}if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)&&!document.querySelector('dialog[open]')){event.preventDefault();if(location.pathname!=='/')goHome();$('query').focus();}});
function identity(){const user=state.user,signed=!!user;if(mcpCredential.owner!==(user?state.csrf:null))resetMCPCredential();$('login-trigger').hidden=signed;$('user-control').hidden=!signed;$('profile-nav').hidden=!signed;if(!user){for(const id of ['menu-name','profile-name','account-name','profile-id','account-id'])$(id).textContent='';$('users-table').replaceChildren();$('bindings').replaceChildren();return;}const initial=Array.from(user.username)[0].toUpperCase();['avatar','profile-avatar','account-avatar','menu-avatar'].forEach(id=>$(id).textContent=initial);['menu-name','profile-name','account-name'].forEach(id=>$(id).textContent=user.username);$('profile-role').textContent=$('account-role').textContent=user.is_admin?'管理员':'成员';$('profile-id').textContent=$('account-id').textContent='账号 ID · '+(user.id||'—');$('users-tab').hidden=!user.can_manage_users;$('menu-account-label').textContent=(user.is_admin?'管理员':'成员')+' · ID '+(user.id||'—');$('mcp-url').textContent=mcpServiceURL();$('account-status').textContent=user.account_status==='active'?'正常':'已登录';renderQuota();}
function renderQuota(){updateMenuTheme();const quota=state.user?.quota;if(!quota)return;const unlimited=!!quota.unlimited,remaining=unlimited?'不限':quota.remaining,limit=unlimited?'不限':quota.daily_limit,reset=quota.resets_at?'下次重置：'+new Date(quota.resets_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})+'（北京时间）'+(quota.in_progress?' · '+quota.in_progress+' 次搜索处理中':''):'';$('account-remaining').textContent=remaining;$('account-used').textContent=quota.used;$('account-limit').textContent=limit;$('account-remaining-row').hidden=unlimited;$('account-usage-row').hidden=unlimited;$('account-unlimited-row').hidden=!unlimited;$('account-unlimited-used').textContent='今日已用 '+quota.used+' 次';$('account-progress').hidden=unlimited;$('account-progress').max=unlimited?1:Math.max(quota.daily_limit,1);$('account-progress').value=unlimited?0:Math.min(quota.used,quota.daily_limit);$('account-reset').hidden=unlimited;$('account-reset').textContent=reset;}
async function showAccount(){setMenu(false);if(!state.user){openLogin(()=>showAccount());return;}try{const user=await api('/api/session');if(!user.username){state.user=null;identity();openLogin(()=>showAccount());return;}state.user={...state.user,...user};state.csrf=user.csrf;identity();$('account-dialog').showModal();}catch(error){toast(message(error));}}
$('account-info-trigger').addEventListener('click',showAccount);$('profile-account-info').addEventListener('click',showAccount);$('close-account').addEventListener('click',()=>$('account-dialog').close());
function openLogin(action=null){setMenu(false);$('login-dialog').returnValue='';pendingAction=action;$('login-error').textContent='';if(!$('login-dialog').open)$('login-dialog').showModal();}
$('login-trigger').addEventListener('click',()=>openLogin());$('close-login').addEventListener('click',()=>$('login-dialog').close());
$('login-dialog').addEventListener('close',()=>{$('login-form').querySelector('[name=password]').value='';if($('login-dialog').returnValue!=='authenticated'){pendingJob=null;pendingAction=null;if(location.pathname==='/profile'){history.replaceState({},'','/');showHome();setResultMode(false);}}});
async function boot(){try{const data=await api('/api/session');state.csrf=data.csrf;state.user=data.username?data:null;state.savedPrefs={...defaults,theme:window.ResourceTheme.preference,...(data.preferences||{})};if(!pendingJob&&!pendingAction)state.prefs=clone(state.savedPrefs);identity();theme(state.prefs.theme);renderSettings();if(state.user)await loadHistory();else{state.history=[];renderHistory();}await restoreURL();}catch(error){toast(message(error));}}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;$('login-error').textContent='';try{const data=await post('/api/login',Object.fromEntries(new FormData(form)));state.user=data;state.csrf=data.csrf;state.savedPrefs={...defaults,...data.preferences};if(!pendingJob&&!pendingAction){state.prefs=clone(state.savedPrefs);renderSettings();theme(state.prefs.theme);}identity();form.reset();$('login-dialog').close('authenticated');await loadHistory();const action=pendingAction,job=pendingJob;pendingAction=null;pendingJob=null;if(job)await runSearch(job.query,job.path,job.extra,job.context);else if(action)await action();else await restoreURL();}catch(error){$('login-error').textContent=message(error);if(error.status===403){const session=await api('/api/session').catch(()=>null);if(session)state.csrf=session.csrf;}}finally{button.disabled=false;}});
async function logout(){try{await post('/api/logout');for(const id of ['account-dialog','modal'])if($(id).open)$(id).close();state.user=null;identity();state.rows=[];state.search=null;state.history=[];state.cache.clear();pendingJob=null;pendingAction=null;setMenu(false);goHome();await boot();toast('已退出登录');}catch(error){toast(message(error));}}
$('logout-button').addEventListener('click',logout);$('account-logout').addEventListener('click',logout);
function cancelSearch(){stopWaitingAnimation();if(searchController)searchController.abort();state.epoch++;state.busy=false;$('search-button').disabled=false;$('search-button').querySelector('span').textContent='搜索';}
function route(url,replace=false){cancelSearch();toggleSettings(false);history[replace?'replaceState':'pushState']({},'',url);window.scrollTo({top:0,behavior:'instant'});restoreURL();}
function goHome(){if(searchController)searchController.abort();state.epoch++;state.busy=false;route('/');}
function goProfile(tab='history'){setMenu(false);if($('account-dialog').open)$('account-dialog').close();if(!state.user){openLogin(()=>goProfile(tab));return;}route('/profile'+(tab!=='history'?'?tab='+tab:''));}
window.addEventListener('click',event=>{const link=event.target.closest('a[data-home],a[data-profile]');if(!link||event.metaKey||event.ctrlKey||event.shiftKey)return;event.preventDefault();link.hasAttribute('data-home')?goHome():goProfile();});
window.addEventListener('popstate',()=>{cancelSearch();restoreURL();});
function conditionsFromURL(params){const prefs={...state.savedPrefs,src:'all',plugins:[],channels:[],sort:'relevance',include_words:'',exclude_words:'',match_mode:'any'};if([10,20,50].includes(Number(params.get('size'))))prefs.page_size=Number(params.get('size'));for(const[key,param]of[['cloud_types','types'],['plugins','plugins'],['channels','channels']])if(params.has(param))prefs[key]=params.get(param).split(',').filter(Boolean);for(const[key,param,allowed]of[['sort','sort',['relevance','newest']],['src','src',['all','tg','plugin']],['match_mode','match',['any','all']]])if(allowed.includes(params.get(param)))prefs[key]=params.get(param);if(params.has('inc'))prefs.include_words=params.get('inc').slice(0,200);if(params.has('exc'))prefs.exclude_words=params.get('exc').slice(0,200);if(params.has('invalid'))prefs.hide_invalid=params.get('invalid')==='hide';return prefs;}
function searchURL(query,options,{sid='',rid='',binding='',page=0,refresh=false}={}){const url=new URL('/',location.origin);url.searchParams.set('q',query);if(refresh)url.searchParams.set('refresh','1');if(options.page_size!==20)url.searchParams.set('size',options.page_size);url.searchParams.set('types',options.cloud_types.join(','));if(options.src!=='all')url.searchParams.set('src',options.src);for(const key of ['plugins','channels'])if(options[key].length)url.searchParams.set(key,options[key].join(','));if(options.sort!=='relevance')url.searchParams.set('sort',options.sort);if(options.match_mode!=='any')url.searchParams.set('match',options.match_mode);if(options.include_words)url.searchParams.set('inc',options.include_words);if(options.exclude_words)url.searchParams.set('exc',options.exclude_words);if(options.hide_invalid)url.searchParams.set('invalid','hide');if(sid)url.searchParams.set('sid',sid);if(rid)url.searchParams.set('rid',rid);if(binding)url.searchParams.set('binding',binding);if(page)url.searchParams.set('page',page+1);return url.pathname+url.search;}
function syncURL(){if(location.pathname!=='/'||!state.search)return;history.replaceState({},'',searchURL(state.search.query,state.prefs,{sid:state.search.search_id,rid:state.search.request_id,binding:state.search.source_binding||'',page:state.page}));}
function setResultMode(active){if(active)collapseSettings();document.body.classList.toggle('has-results',active);$('results-region').hidden=!active;$('home-history').hidden=active||!state.history.length;}
function showHome(){document.body.classList.remove('on-profile');$('home-view').hidden=false;$('profile-view').hidden=true;document.title='Resource Hub';}
async function restoreURL(){collapseSettings();const params=new URLSearchParams(location.search);if(location.pathname==='/profile'){if(!state.user){showHome();setResultMode(false);openLogin(()=>restoreURL());return;}$('home-view').hidden=true;$('profile-view').hidden=false;document.body.classList.add('on-profile');document.body.classList.remove('has-results');accountTab(params.get('tab')||'history',false);document.title=state.user.username+' · Resource Hub';return;}showHome();if(location.hash){if(location.hash==='#settings')toggleSettings(true);history.replaceState({},'',location.pathname+location.search);}const query=params.get('q')||'';state.prefs=conditionsFromURL(params);renderSettings();$('query').value=query;updateClear();if(!query){state.search=null;state.rows=[];$('results').replaceChildren();setResultMode(false);renderHistory();return;}document.title=query+' · Resource Hub';setResultMode(true);if(!state.user){renderStatus('登录后查看搜索结果','使用你的账号继续这次搜索',[['登录',()=>openLogin(()=>restoreURL())]]);return;}const sid=params.get('sid');if(sid){const epoch=++state.epoch;renderStatus('正在恢复搜索结果','');try{let data=state.cache.get(sid);if(!data)data=await api('/api/results/'+encodeURIComponent(sid));if(epoch!==state.epoch)return;state.page=Math.max(0,(parseInt(params.get('page'),10)||1)-1);setResults(data,false);return;}catch(error){if(epoch!==state.epoch)return;renderStatus('搜索记录暂时无法恢复',message(error),[['重试',()=>restoreURL()],['重新搜索',()=>runSearch(query)]]);return;}}await runSearch(query,params.get('binding')?'/api/bindings/'+encodeURIComponent(params.get('binding')):'/api/search',{refresh:params.get('refresh')==='1'}, {rid:params.get('rid')||requestId(),replace:true,restoring:true});}
function updateClear(){$('clear-query').hidden=!$('query').value;}
$('query').addEventListener('input',()=>{updateClear();$('input-error').hidden=true;});$('clear-query').addEventListener('click',()=>{$('query').value='';updateClear();$('query').focus();});
$('search-form').addEventListener('submit',event=>{event.preventDefault();runSearch($('query').value);});
$('results').addEventListener('click',event=>{if(event.target.closest('a,button'))return;const row=event.target.closest('.result-row'),link=row?.querySelector('.result-title');if(link?.href)window.open(link.href,'_blank','noopener,noreferrer');});
function renderStatus(title,description='',actions=[]){stopWaitingAnimation();$('skeleton').hidden=true;$('result-toolbar').hidden=true;$('pagination').hidden=true;$('results').replaceChildren();$('search-status').hidden=false;$('search-status').replaceChildren(node('h2',{text:title}),...(description?[node('p',{text:description})]:[]),...(actions.length?[node('div',{class:'status-actions'},actions.map(([text,action],i)=>node('button',{class:i?'text-button':'secondary',text,onclick:action})))]:[]));}
function stopWaitingAnimation(){clearInterval(waitingTimer);waitingTimer=null;}
function loading(){stopWaitingAnimation();setResultMode(true);$('search-status').hidden=false;const phase=node('p',{class:'waiting-caption',text:'正在查找相关资源'}),elapsed=node('span',{class:'waiting-elapsed','aria-hidden':'true',text:'请稍候'});$('search-status').replaceChildren(node('div',{class:'waiting-state'},[node('img',{class:'waiting-gears',src:'/assets/search-gears.svg',alt:'','aria-hidden':'true'}),node('h2',{text:'正在搜索'}),phase,elapsed]));const started=performance.now();waitingTimer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);elapsed.textContent='已等待 '+seconds+' 秒';phase.textContent=seconds>=12?'仍在等待搜索来源返回结果':seconds>=5?'搜索还在进行，请稍候':'正在查找相关资源';},1000);$('result-toolbar').hidden=true;$('pagination').hidden=true;$('results').replaceChildren();$('skeleton').hidden=false;$('skeleton').replaceChildren(...Array.from({length:3},()=>node('div',{class:'skeleton-row'},[node('span',{class:'skeleton-icon'}),node('div',{class:'skeleton-content'},[node('div',{class:'skeleton-line'}),node('div',{class:'skeleton-line short'})])])));$('results-region').setAttribute('aria-busy','true');}
async function runSearch(query,path='/api/search',extra={},context={}){query=query.trim();if(!query){$('input-error').textContent='请输入搜索关键词';$('input-error').hidden=false;$('query').focus();return;}if(state.busy)return;collapseSettings();const options=clone(context.options||state.prefs),rid=context.rid||requestId();if(!state.user){pendingJob={query,path,extra,context:{...context,options,rid}};openLogin();return;}const epoch=++state.epoch;searchController=new AbortController();state.busy=true;state.job={query,path,extra,context:{...context,options,rid,replace:true}};$('query').value=query;updateClear();$('input-error').hidden=true;$('search-button').disabled=true;$('search-button').querySelector('span').textContent='搜索中';state.search=null;if(location.pathname==='/profile')window.scrollTo({top:0,behavior:'instant'});const binding=path.startsWith('/api/bindings/')?decodeURIComponent(path.split('/').pop()):'';history[context.replace?'replaceState':'pushState']({},'',searchURL(query,options,{rid,binding,refresh:!!extra.refresh}));showHome();loading();const start=performance.now();try{const payload=path==='/api/search'?{query,request_id:rid,options,...extra}:{action:'test_search',keyword:query,request_id:rid,...extra};let data=await post(path,payload,{signal:searchController.signal});if(data.available_count>data.results.length)data=await api('/api/results/'+encodeURIComponent(data.search_id),{signal:searchController.signal});if(epoch!==state.epoch)return;data.elapsed=((performance.now()-start)/1000).toFixed(1);data.source_binding=binding;state.prefs=options;state.page=0;setResults(data);loadHistory();}catch(error){if(epoch!==state.epoch||error.name==='AbortError')return;state.rows=[];if(error.status===401){state.user=null;identity();pendingJob=state.job;renderStatus('登录已过期','重新登录后继续搜索',[['重新登录',()=>openLogin()]]);}else if(error.code==='daily_limit_reached')renderStatus('今日搜索次数已用完','可以在账户信息中查看额度和重置时间',[['查看账户信息',showAccount]]);else renderStatus('这次搜索未能完成',message(error),[['重试',()=>runSearch(query,path,extra,{...context,options,rid,replace:true})],['修改设置',()=>toggleSettings(true)]]);}finally{if(epoch===state.epoch){stopWaitingAnimation();state.busy=false;$('search-button').disabled=false;$('search-button').querySelector('span').textContent='搜索';$('results-region').setAttribute('aria-busy','false');}}}
function setResults(data,writeURL=true){stopWaitingAnimation();state.search=data;state.rows=data.results||[];state.cache.set(data.search_id,data);state.checks.clear();$('query').value=data.query||'';updateClear();$('search-status').hidden=true;$('skeleton').hidden=true;$('results-region').setAttribute('aria-busy','false');$('result-toolbar').hidden=false;$('sort-results').value=state.prefs.sort;setResultMode(true);renderResults(true);if(writeURL)syncURL();document.title=(data.query||'搜索')+' · Resource Hub';}
function filteredRows(){const include=words(state.prefs.include_words),exclude=words(state.prefs.exclude_words);const rows=state.rows.filter(row=>{const text=(row.title+' '+row.source).toLowerCase();return(!include.length||(state.prefs.match_mode==='all'?include.every(word=>text.includes(word)):include.some(word=>text.includes(word))))&&!exclude.some(word=>text.includes(word))&&!(state.prefs.hide_invalid&&state.checks.get(row.url)?.state==='bad');});if(state.prefs.sort==='newest')rows.sort((a,b)=>(Date.parse(b.datetime)||0)-(Date.parse(a.datetime)||0));return rows;}
function highlighted(text,query){const fragment=document.createDocumentFragment(),index=text.toLowerCase().indexOf(query.toLowerCase());if(index<0||!query){fragment.append(text);return fragment;}fragment.append(text.slice(0,index),node('mark',{text:text.slice(index,index+query.length)}),text.slice(index+query.length));return fragment;}
function renderResults(animate=false){window.ResourceSelect?.sync();if(!state.search)return;const rows=filteredRows(),size=state.prefs.page_size,total=Math.max(1,Math.ceil(rows.length/size));state.page=Math.min(state.page,total-1);const visible=rows.slice(state.page*size,(state.page+1)*size);$('results').className='result-list'+(animate?'':' settled');$('result-count').textContent=rows.length+' 条'+(state.search.elapsed?' · '+state.search.elapsed+' 秒':'');$('search-status').hidden=true;$('results').replaceChildren(...visible.map(row=>{const url=safeUrl(row.url),meta=[node('span',{class:'disk-label',text:clouds[row.cloud_type]||row.cloud_type})];if(row.source)meta.push(node('span',{text:row.source.replace(/^plugin:/,'')}));if(row.datetime)meta.push(node('span',{text:row.datetime.slice(0,10)}));if(row.password)meta.push(node('button',{class:'text-button',text:'提取码 '+row.password,onclick:()=>clipboard(row.password)}));const check=state.checks.get(row.url);if(row.url.startsWith('http'))meta.push(node('button',{class:'text-button check-state '+(check?.state||''),text:check?({ok:'有效',good:'有效',bad:'已失效',checking:'检测中',unknown:'未确定'}[check.state]||'未确定'):'检测链接',title:check?.summary||'检查分享链接状态',onclick:()=>checkVisible([row])}));return node('article',{class:'result-row','data-cloud':row.cloud_type||'others'},[node('div',{class:'result-head'},[node('span',{class:'disk-icon','aria-hidden':'true',text:(clouds[row.cloud_type]||'资源').slice(0,2)}),node('div',{class:'result-main'},[node(url?'a':'span',{class:'result-title',...(url?{href:url,target:'_blank',rel:'noopener noreferrer'}:{})},[highlighted(row.title||'未命名资源',state.search.query)]),node('div',{class:'result-meta'},meta)])]),node('div',{class:'result-actions'},[node('button',{class:'text-button',text:'复制链接',onclick:()=>clipboard(row.url+(row.password?'\n提取码：'+row.password:''))}),...(url?[node('a',{class:'open-link',href:url,target:'_blank',rel:'noopener noreferrer',text:'','aria-label':'打开 '+row.title})]:[])])]);}));if(!visible.length){renderStatus(state.rows.length?'没有符合条件的结果':'暂时没有找到相关资源',state.rows.length?'可以减少包含条件，或放宽有效性筛选':'试试缩短关键词、使用作品正式名称，或扩大资源来源',[[state.rows.length?'清除结果筛选':'修改关键词',()=>{if(state.rows.length){state.prefs.include_words='';state.prefs.exclude_words='';state.prefs.hide_invalid=false;renderSettings();renderResults(true);syncURL();}else $('query').focus();}],['搜索设置',()=>toggleSettings(true)]]);$('result-toolbar').hidden=false;}$('pagination').hidden=total<=1;$('pagination').replaceChildren(node('button',{text:' 上一页',disabled:state.page===0,onclick:()=>pageTo(state.page-1)}),node('span',{text:(state.page+1)+' / '+total}),node('button',{text:'下一页',disabled:state.page===total-1,onclick:()=>pageTo(state.page+1)}));if((state.prefs.auto_check||state.prefs.hide_invalid)&&!state.checking){const pending=visible.filter(row=>row.url.startsWith('http')&&!state.checks.has(row.url)).slice(0,20);if(pending.length)checkVisible(pending,true);}}
function pageTo(page){state.page=page;renderResults(true);syncURL();$('result-toolbar').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});}
async function checkVisible(rows,automatic=false){rows=rows.filter(row=>row.url.startsWith('http')).slice(0,20);if(!rows.length||!state.search)return;const id=state.search.search_id;state.checking=true;rows.forEach(row=>state.checks.set(row.url,{state:'checking'}));renderResults();try{const data=await post('/api/check',{search_id:id,urls:rows.map(row=>row.url)});if(state.search?.search_id!==id)return;rows.forEach((row,index)=>state.checks.set(row.url,data.results[index]));}catch(error){if(state.search?.search_id!==id)return;rows.forEach(row=>state.checks.set(row.url,{state:'unknown',summary:message(error)}));if(!automatic)toast(message(error));}finally{state.checking=false;if(state.search?.search_id===id)renderResults();}}
$('sort-results').addEventListener('change',()=>{state.prefs.sort=$('sort-results').value;$('default-sort').value=state.prefs.sort;state.page=0;renderResults();updateSettingsState();syncURL();});$('refresh-results').addEventListener('click',()=>{if(state.search)runSearch(state.search.query,'/api/search',{refresh:true});});
function collapseSettings(){if($('search-settings').open)toggleSettings(false);}
function syncSettingsDialog(){
  const open=$('search-settings').open;
  document.body.classList.toggle('settings-open',open);
  $('settings-toggle').setAttribute('aria-expanded',String(open));
}
function toggleSettings(open){
  const dialog=$('search-settings');
  if(open===dialog.open)return;
  window.ResourceSelect?.close();
  if(open){
    setMenu(false);
    dialog.showModal();
    dialog.querySelector('.settings-body').scrollTop=0;
    if(state.user&&!state.catalog.loaded)loadCatalog();
  }else dialog.close();
  syncSettingsDialog();
}
$('settings-toggle').addEventListener('click',()=>toggleSettings(true));
$('collapse-settings').addEventListener('click',()=>toggleSettings(false));
$('search-settings').addEventListener('close',()=>{
  syncSettingsDialog();
  if($('search-settings').open)return;
  window.ResourceSelect?.close();
  renderResults();
  syncURL();
  if(!document.querySelector('dialog[open]'))$('settings-toggle').focus({preventScroll:true});
});
$('search-settings').addEventListener('click',event=>{
  if(event.target!==event.currentTarget)return;
  const bounds=event.currentTarget.getBoundingClientRect();
  if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)toggleSettings(false);
});
function renderSettings(){const prefs=state.prefs;$('settings-clouds').replaceChildren(...Object.entries(clouds).map(([value,label])=>node('label',{class:'choice-item'},[node('input',{type:'checkbox',value,checked:prefs.cloud_types.includes(value)}),document.createTextNode(label)])));$('source-mode').value=prefs.src;$('plugin-input').value=prefs.plugins.join(', ');$('channel-input').value=prefs.channels.join('\n');$('page-size').value=prefs.page_size;$('default-sort').value=prefs.sort;$('theme').value=prefs.theme;$('auto-check').checked=prefs.auto_check;$('hide-invalid').checked=prefs.hide_invalid;$('include-words').value=prefs.include_words;$('exclude-words').value=prefs.exclude_words;$('match-mode').value=prefs.match_mode;renderCatalog();updateSettingsState();window.ResourceSelect?.sync();}
function collectSettings(){return{cloud_types:[...$('settings-clouds').querySelectorAll('input:checked')].map(input=>input.value),channels:splitNames($('channel-input').value),plugins:splitNames($('plugin-input').value),src:$('source-mode').value,page_size:Number($('page-size').value),sort:$('default-sort').value,theme:$('theme').value,auto_check:$('auto-check').checked,hide_invalid:$('hide-invalid').checked,include_words:$('include-words').value,exclude_words:$('exclude-words').value,match_mode:$('match-mode').value};}
function updateSettingsState(note=''){const dirty=JSON.stringify(state.prefs)!==JSON.stringify(state.savedPrefs);$('settings-dirty').textContent=note||(dirty?'未保存':'');$('settings-dirty').className='save-state'+(dirty?' dirty':'');$('settings-summary').textContent=(state.prefs.cloud_types.length?state.prefs.cloud_types.map(id=>clouds[id]||id).join('、'):'全部网盘')+' · '+({all:'全部来源',tg:'频道',plugin:'插件'}[state.prefs.src])+(state.prefs.sort==='newest'?' · 最新发布':'');}
function settingsChanged(refreshCatalog=false){state.prefs=collectSettings();theme(state.prefs.theme);state.page=0;if(refreshCatalog)renderCatalog();updateSettingsState();if(!$('search-settings').open){renderResults();syncURL();}}
$('search-settings').addEventListener('change',event=>{if(event.target.id!=='import-config')settingsChanged(['plugin-input','channel-input'].includes(event.target.id));});$('search-settings').addEventListener('input',event=>{if(['include-words','exclude-words','plugin-input','channel-input'].includes(event.target.id))settingsChanged(['plugin-input','channel-input'].includes(event.target.id));});
async function saveSettings(){if(!state.user){openLogin(saveSettings);return;}const button=$('save-settings');button.disabled=true;$('settings-dirty').textContent='正在保存';try{const saved=await api('/api/preferences',{method:'PUT',body:JSON.stringify(collectSettings())});state.prefs={...defaults,...saved};state.savedPrefs=clone(state.prefs);updateSettingsState('已保存');toggleSettings(false);toast('设置已保存');}catch(error){$('settings-dirty').textContent='保存失败';$('settings-dirty').className='save-state error';toast(message(error));}finally{button.disabled=false;}}
$('save-settings').addEventListener('click',saveSettings);$('reset-settings').addEventListener('click',()=>{state.prefs=clone(defaults);state.page=0;renderSettings();theme('light');updateSettingsState('已恢复默认，尚未保存');});$('select-all-clouds').addEventListener('click',()=>{const inputs=[...$('settings-clouds').querySelectorAll('input')],checked=!inputs.every(input=>input.checked);inputs.forEach(input=>input.checked=checked);settingsChanged();});
async function loadCatalog(){if(!state.user){$('catalog-status').textContent='登录后读取可用搜索源';return;}$('catalog-status').textContent='正在读取搜索源';try{state.catalog={...await api('/api/catalog'),loaded:true};renderCatalog();$('catalog-status').textContent='已读取可用搜索源';}catch(error){$('catalog-status').textContent=message(error);}}
function renderCatalog(){for(const[key,inputId,target]of[['plugins','plugin-input','plugin-choices'],['channels','channel-input','channel-choices']])$(target).replaceChildren(...(state.catalog[key]||[]).map(value=>node('button',{class:'chip',type:'button',text:value,'aria-pressed':String(splitNames($(inputId).value).includes(value)),onclick:()=>{const values=new Set(splitNames($(inputId).value));values.has(value)?values.delete(value):values.add(value);$(inputId).value=[...values].join(', ');settingsChanged(true);}})));}
$('reload-catalog').addEventListener('click',loadCatalog);
let historyVersion=0;
async function loadHistory(){if(!state.user)return;const owner=state.user.username,version=++historyVersion;try{const data=await api('/api/history');if(state.user?.username!==owner||version!==historyVersion)return;state.history=data.items;renderHistory();}catch(error){if(state.user?.username===owner&&version===historyVersion&&location.pathname==='/profile')$('profile-history').replaceChildren(node('p',{class:'field-help',text:message(error)}));}}
function renderHistory(){
  $('clear-history').hidden=!state.history.length;
  $('recent-searches').replaceChildren(...state.history.slice(0,4).map(item=>node('button',{class:'history-chip',text:item.query,onclick:()=>loadResult(item.id)})));
  $('home-history').hidden=!state.history.length||document.body.classList.contains('has-results');
  $('profile-history').replaceChildren(...state.history.map(item=>node('article',{class:'history-row'},[
    node('div',{},[node('button',{class:'history-title',type:'button',text:item.query,onclick:()=>loadResult(item.id)}),node('p',{text:new Date(item.created*1000).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})})]),
    historyDeleteButton(item)
  ])));
  if(!state.history.length)$('profile-history').append(node('div',{class:'profile-empty'},[node('h3',{text:'还没有搜索记录'}),node('p',{text:'从一个关键词开始，你的搜索会记录在这里'}),node('a',{href:'/',class:'secondary','data-home':'',text:'开始搜索'})]));
}
function historyDeleteButton(item){
  const button=node('button',{class:'icon-button history-delete',type:'button','aria-label':'删除搜索记录 '+item.query,title:'删除记录'});
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6m4-6v6');svg.append(path);button.append(svg);
  button.addEventListener('click',()=>deleteHistory(item,button));return button;
}
let historyDeleteBusy=false;
async function deleteHistory(item,button,owner=state.user?.username){
  if(!owner||state.user?.username!==owner||historyDeleteBusy)return;
  historyDeleteBusy=true;button.disabled=true;
  document.querySelectorAll('.history-delete,#clear-history').forEach(control=>control.disabled=true);
  const modalAction=button.closest('#modal');
  try{
    const data=await api('/api/history'+(item?'/'+encodeURIComponent(item.id):''),{method:'DELETE'});
    if(state.user?.username!==owner)return;
    ++historyVersion;
    for(const id of data.deleted_ids)state.cache.delete(id);
    if(data.deleted_ids.includes(state.search?.search_id)){
      state.search=null;state.rows=[];state.checks.clear();$('results').replaceChildren();$('query').value='';updateClear();setResultMode(false);
    }
    state.history=data.items;renderHistory();if(modalAction&&button.isConnected)closeModal();
    if(location.pathname==='/profile'&&state.tab==='history'&&!document.querySelector('dialog[open]'))($('profile-history').querySelector('.history-delete')||$('refresh-history')).focus({preventScroll:true});
    toast(item?'搜索记录已删除':'搜索记录已清空');
  }catch(error){toast(message(error));}finally{
    historyDeleteBusy=false;button.disabled=false;document.querySelectorAll('.history-delete,#clear-history').forEach(control=>control.disabled=false);
  }
}
function confirmClearHistory(){
  const owner=state.user?.username;if(!owner||historyDeleteBusy)return;
  const button=node('button',{class:'primary',type:'button',text:'清空记录'});
  const content=node('div',{},[
    node('p',{class:'field-help',text:'确定清空全部搜索记录？'}),
    node('div',{class:'form-actions'},[node('button',{class:'secondary',type:'button',text:'取消',autofocus:'',onclick:closeModal}),button])
  ]);
  button.addEventListener('click',()=>deleteHistory(null,button,owner));openModal('清空搜索记录',content);
}
$('clear-history').addEventListener('click',confirmClearHistory);
async function loadResult(id){try{const data=await api('/api/results/'+encodeURIComponent(id));state.cache.set(id,data);const options={...state.prefs,...(data.options||{})};route(searchURL(data.query,options,{sid:id,rid:data.request_id,binding:data.source_binding||''}));}catch(error){toast(message(error));}}
$('refresh-history').addEventListener('click',loadHistory);
function accountTab(tab,write=true){if(!['history','sources','security','users'].includes(tab)||(tab==='users'&&!state.user?.can_manage_users))tab='history';state.tab=tab;document.querySelectorAll('[data-account-panel]').forEach(panel=>panel.hidden=panel.dataset.accountPanel!==tab);document.querySelectorAll('[data-account-tab]').forEach(button=>{const active=button.dataset.accountTab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});if(write)history.replaceState({},'','/profile'+(tab==='history'?'':'?tab='+tab));if(tab==='history')loadHistory();if(tab==='sources')loadBindings();if(tab==='users')loadUsers();if(tab==='security')updateMCPCredential();}
const tabs=[...document.querySelectorAll('[data-account-tab]')];tabs.forEach(button=>{button.addEventListener('click',()=>accountTab(button.dataset.accountTab));button.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const visible=tabs.filter(tab=>!tab.hidden),index=visible.indexOf(button),next=event.key==='Home'?0:event.key==='End'?visible.length-1:(index+(event.key==='ArrowRight'?1:-1)+visible.length)%visible.length;visible[next].focus();accountTab(visible[next].dataset.accountTab);});});
$('password-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,data=Object.fromEntries(new FormData(form));if(data.password!==data.confirm){toast('两次输入的密码不一致');return;}try{await post('/api/password',data);form.reset();state.user=null;identity();await boot();openLogin(()=>goProfile('security'));toast('密码已更新，请重新登录');}catch(error){toast(message(error));}});
let mcpCredential={owner:null,token:'',active:false,expires:null,busy:false,loaded:false,version:0};
function mcpServiceURL(){return state.user?(state.user.mcp_url||new URL('/mcp',location.origin).href):'';}
function resetMCPCredential(){
  mcpCredential={owner:state.user?state.csrf:null,token:'',active:false,expires:null,busy:false,loaded:false,version:mcpCredential.version+1};
  $('mcp-url').textContent=mcpServiceURL();$('mcp-token').type='password';$('toggle-mcp-token').textContent='显示';$('toggle-mcp-token').setAttribute('aria-pressed','false');renderMCPCredential();
}
function renderMCPCredential(){
  const value=mcpCredential;
  $('mcp-url').textContent=mcpServiceURL();$('copy-mcp').disabled=!state.user;
  $('mcp-token').value=value.token;
  $('mcp-token').placeholder=value.active?'原 Token 无法恢复，请重新生成':'生成后显示 Token';
  $('copy-mcp-token').disabled=$('toggle-mcp-token').disabled=!value.token||value.busy;
  $('generate-mcp-token').disabled=value.busy||!state.user;
  $('generate-mcp-token').textContent=value.busy?'处理中…':!value.loaded?'重试连接':value.active?'重置 Token':'生成 Token';
  $('revoke-mcp-token').disabled=!value.active||value.busy;
  $('mcp-token-status').textContent=value.busy?'处理中…':!value.loaded?'正在读取…':value.active?'有效期至 '+new Date(value.expires*1000).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚未生成 Token';
}
async function updateMCPCredential(method='GET'){
  if(!state.user||mcpCredential.busy)return;
  const owner=mcpCredential.owner,version=++mcpCredential.version;
  mcpCredential.busy=true;renderMCPCredential();
  try{
    const data=await api('/api/mcp-token',{method});
    if(owner!==mcpCredential.owner||version!==mcpCredential.version)return;
    if(data.token!==mcpCredential.token||!data.active||data.expires_at!==mcpCredential.expires){mcpCredential.token=data.token||'';$('mcp-token').type='password';$('toggle-mcp-token').textContent='显示';$('toggle-mcp-token').setAttribute('aria-pressed','false');}
    if(data.mcp_url)state.user.mcp_url=data.mcp_url;
    Object.assign(mcpCredential,{active:data.active,expires:data.expires_at,loaded:true});
    if(method==='POST')toast('Token 已生成，可复制到 MCP 客户端');
    if(method==='DELETE')toast('Token 已撤销');
  }catch(error){
    if(owner!==mcpCredential.owner||version!==mcpCredential.version)return;
    // A lost mutation response may still have rotated/revoked the token on the server.
    if(method!=='GET'){mcpCredential.token='';mcpCredential.loaded=false;}
    toast(message(error));
  }finally{
    if(owner===mcpCredential.owner&&version===mcpCredential.version){mcpCredential.busy=false;renderMCPCredential();if(!mcpCredential.loaded)$('mcp-token-status').textContent='状态未确认，请重试连接';}
  }
}
function confirmMCPAction(title,description,action,label){
  const owner=mcpCredential.owner;
  const button=node('button',{class:'primary',type:'button',text:label,onclick:async()=>{if(owner!==mcpCredential.owner){closeModal();return;}button.disabled=true;try{await action();closeModal();}finally{button.disabled=false;}}});
  openModal(title,node('div',{},[node('p',{class:'field-help',text:description}),node('div',{class:'form-actions'},[node('button',{class:'secondary',type:'button',text:'取消',autofocus:'',onclick:closeModal}),button])]));
}
$('copy-mcp').addEventListener('click',()=>{if(state.user)clipboard(mcpServiceURL());});
$('copy-mcp-token').addEventListener('click',()=>{if(mcpCredential.token)clipboard(mcpCredential.token);});
$('toggle-mcp-token').addEventListener('click',()=>{const reveal=$('mcp-token').type==='password';$('mcp-token').type=reveal?'text':'password';$('toggle-mcp-token').textContent=reveal?'隐藏':'显示';$('toggle-mcp-token').setAttribute('aria-pressed',String(reveal));});
$('generate-mcp-token').addEventListener('click',()=>{
  if(!mcpCredential.loaded){updateMCPCredential();return;}
  if(mcpCredential.active)confirmMCPAction('重置 Token','原 Token 将失效，请同步更新客户端配置。',()=>updateMCPCredential('POST'),'重置');
  else updateMCPCredential('POST');
});
$('revoke-mcp-token').addEventListener('click',()=>confirmMCPAction('撤销 Token','撤销后，使用此 Token 的客户端将无法连接。',()=>updateMCPCredential('DELETE'),'撤销'));
$('export-config').addEventListener('click',()=>download('resource-hub-settings.json',JSON.stringify(collectSettings(),null,2)));
$('import-config').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>10000)throw new Error();const data=JSON.parse(await file.text());if(!data||typeof data!=='object'||Array.isArray(data))throw new Error();for(const key of ['cloud_types','plugins','channels'])if(!Array.isArray(data[key])||data[key].some(value=>typeof value!=='string'))throw new Error();const next={...defaults,...Object.fromEntries(Object.keys(defaults).filter(key=>key in data).map(key=>[key,data[key]]))};if(!['light','dark','system'].includes(next.theme)||![10,20,50].includes(next.page_size)||!['any','all'].includes(next.match_mode)||!['all','tg','plugin'].includes(next.src)||!['relevance','newest'].includes(next.sort))throw new Error();for(const key of ['auto_check','hide_invalid'])if(typeof next[key]!=='boolean')throw new Error();for(const key of ['include_words','exclude_words'])if(typeof next[key]!=='string'||next[key].length>200)throw new Error();if(next.cloud_types.some(value=>!Object.hasOwn(clouds,value)))throw new Error();state.prefs=next;renderSettings();theme(next.theme);toast('配置已载入，保存后生效');}catch{toast('配置文件格式不正确');}event.target.value='';});
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
  const form=node('form');form.append(node('p',{class:'muted small',text:'导出当前筛选结果，共 '+filteredRows().length+' 条'}));
  const select=node('select',{name:'format'},[['txt','文本 TXT'],['csv','表格 CSV'],['json','JSON']].map(([value,text])=>node('option',{value,text})));
  form.append(field('文件格式',select),node('div',{class:'form-actions'},[node('button',{class:'primary',type:'submit',text:'下载结果'})]));
  form.addEventListener('submit',event=>{event.preventDefault();const rows=filteredRows(),format=select.value;let output;
    if(format==='json')output=JSON.stringify(rows,null,2);
    else if(format==='csv'){const quote=value=>{let text=String(value??'');if(/^[\s]*[=+@-]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};output='\ufeff'+['名称,网盘,链接,提取码,来源,日期',...rows.map(r=>[r.title,clouds[r.cloud_type]||r.cloud_type,r.url,r.password,r.source,r.datetime].map(quote).join(','))].join('\r\n');}
    else output=rows.map(r=>r.title+'\n'+r.url+(r.password?'\n提取码：'+r.password:'')).join('\n\n');
    download('搜索结果.'+format,output,format==='json'?'application/json':'text/plain;charset=utf-8');closeModal();
  });openModal('导出结果',form);
});
function field(label,input){return node('label',{text:label},[input]);}
function splitNames(value){return [...new Set(value.split(/[\s,，]+/).map(v=>v.trim()).filter(Boolean))];}

renderSettings();
window.addEventListener('DOMContentLoaded',boot);

new ResizeObserver(()=>{document.documentElement.style.setProperty('--header-height',document.querySelector('.header').getBoundingClientRect().height+'px');}).observe(document.querySelector('.header'));

function updateMenuTheme(){if(!$('menu-theme-label'))return;$('menu-theme-label').textContent='主题：'+({light:'浅色',dark:'深色',system:'跟随系统'}[state.prefs.theme]||'浅色');document.querySelectorAll('[data-menu-theme]').forEach(button=>button.setAttribute('aria-checked',String(button.dataset.menuTheme===state.prefs.theme)));}
$('menu-theme').addEventListener('click',()=>{const open=$('menu-theme-options').hidden;$('menu-theme-options').hidden=!open;$('menu-theme').setAttribute('aria-expanded',String(open));});
document.querySelectorAll('[data-menu-theme]').forEach(button=>button.addEventListener('click',async()=>{const value=button.dataset.menuTheme,previous=state.prefs.theme;state.prefs.theme=value;theme(value);updateMenuTheme();try{await api('/api/preferences',{method:'PUT',body:JSON.stringify({theme:value})});state.savedPrefs.theme=value;$('theme').value=value;updateSettingsState();toast('主题已保存');}catch(error){state.prefs.theme=previous;theme(previous);updateMenuTheme();toast(message(error));}}));
