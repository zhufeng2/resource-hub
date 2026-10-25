'use strict';
async function loadUsers(){if(!state.user?.can_manage_users)return;const owner=state.user.username;try{const data=await api('/api/users');if(state.user?.username!==owner)return;$('users-table').replaceChildren(...data.items.map(user=>node('tr',{},[node('td',{text:user.username}),node('td',{text:user.is_admin?'管理员':'成员'}),node('td',{text:user.is_admin?'不限':user.daily_limit+' 次'}),node('td',{},[node('span',{class:'pill',text:user.enabled?'正常':'已停用'})]),node('td',{},[node('button',{class:'text-button',text:'编辑 ↗',onclick:()=>userEditor(user)})])])));}catch(error){toast(message(error));}}
function userEditor(user=null){
  const form=node('form'),username=node('input',{name:'username',maxlength:'64',required:'',value:user?.username||'',...(user?{readonly:''}:{})}),password=node('input',{name:'password',type:'password',minlength:'12',maxlength:'256',autocomplete:'new-password',...(!user?{required:''}:{placeholder:'留空保留当前密码'})}),limit=node('input',{name:'daily_limit',type:'number',min:'0',max:'10000',value:user?.daily_limit??5,required:''}),admin=node('input',{name:'is_admin',type:'checkbox',checked:!!user?.is_admin}),enabled=node('input',{name:'enabled',type:'checkbox',checked:user?!!user.enabled:true});
  form.append(field('账号',username),field(user?'重置密码':'密码',password),field('每日搜索额度',limit),node('label',{class:'toggle-row'},[node('span',{text:'管理员权限（不限搜索次数）'}),admin]));if(user)form.append(node('label',{class:'toggle-row'},[node('span',{text:'启用账号'}),enabled]));
  const syncLimit=()=>{limit.disabled=admin.checked;limit.closest('label').hidden=admin.checked;};admin.addEventListener('change',syncLimit);syncLimit();
  form.append(node('div',{class:'form-actions'},[node('button',{type:'button',class:'secondary',text:'取消',onclick:closeModal}),node('button',{type:'submit',class:'primary',text:user?'保存修改':'创建用户'})]));
  form.addEventListener('submit',async(event)=>{event.preventDefault();try{await api('/api/users',{method:user?'PATCH':'POST',body:JSON.stringify({username:username.value,password:password.value,daily_limit:Number(limit.value),is_admin:admin.checked,enabled:enabled.checked})});closeModal();loadUsers();toast(user?'账号已更新':'账号已创建');}catch(error){toast(message(error));}});openModal(user?'编辑账号':'创建用户',form);
}
$('add-user').addEventListener('click',()=>userEditor());
async function loadBindings(){if(!state.user)return;const owner=state.user.username;try{const {items}=await api('/api/bindings');if(state.user?.username!==owner)return;$('bindings').replaceChildren(...items.map(item=>node('article',{class:'binding-card'},[node('div',{class:'disk-icon',text:sources[item.provider].slice(0,2)}),node('h3',{text:item.label}),node('p',{text:sources[item.provider]}),node('div',{class:'binding-bottom'},[node('span',{class:'small-label',text:'账号连接'}),node('button',{class:'text-button',text:'管理 ↗',onclick:()=>bindingEditor(item)})])])));if(!items.length)$('bindings').append(node('p',{class:'muted small',text:'还没有添加搜索源账号。'}));}catch(error){toast(message(error));}}
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
      const input=node('input',{maxlength:'120',required:'',placeholder:'输入关键词测试搜索'}),form=node('form');form.append(node('div',{class:'divider'}),field('测试搜索',input),node('p',{class:'field-help',text:'成功搜索将使用 1 次额度。'}),node('button',{class:'secondary',type:'submit',text:'搜索'}));form.addEventListener('submit',event=>{event.preventDefault();const query=input.value;closeModal();runSearch(query,'/api/bindings/'+encodeURIComponent(binding.id));});area.append(form);
      actions.append(node('button',{class:'text-button',text:'退出搜索源账号',onclick:async()=>{try{const response=await call('logout');if(response.success)refresh();else toast(response.message||'退出失败');}catch(error){toast(message(error));}}}));
    }
    if(['gying','woniu'].includes(binding.provider))actions.append(node('button',{class:'text-button',text:'站点配置',onclick:async()=>{try{const response=await call('get_config');if(!active)return;const input=node('input',{type:'url',value:response.data.base_url||'',readonly:!state.user.is_admin?'':null});area.append(node('div',{class:'divider'}),field('站点地址',input));if(state.user.is_admin)area.append(node('button',{class:'secondary',text:'保存地址',onclick:async()=>{try{const saved=await call('update_config',{base_url:input.value});toast(saved.success?'站点地址已保存':saved.message||'保存失败');}catch(error){toast(message(error));}}}));}catch(error){toast(message(error));}}}));
    actions.append(node('button',{class:'text-button',text:'刷新状态',onclick:refresh}),node('button',{class:'text-button danger-text',text:'移除账号',onclick:async()=>{try{await call('remove');closeModal();loadBindings();toast('账号已移除');}catch(error){toast(message(error));}}}));
  }
  function startPoll(){clearInterval(pollTimer);let attempts=0;pollTimer=setInterval(async()=>{if(!active||++attempts>24){clearInterval(pollTimer);return;}try{const response=await call('check_login');if(!active)return;status.textContent=statusText(response.data);if(response.data.login_status==='success'){clearInterval(pollTimer);refresh();}else if(response.data.login_status==='expired'){clearInterval(pollTimer);}}catch{clearInterval(pollTimer);}},5000);}
  await refresh();
}
