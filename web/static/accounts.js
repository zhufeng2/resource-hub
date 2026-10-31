'use strict';
const usersList={page:1,pages:1,query:'',pageSize:20,request:0,owner:null};
async function loadUsers(){
  if(!state.user?.can_manage_users)return;
  const owner=state.csrf;
  if(usersList.owner!==owner){Object.assign(usersList,{page:1,pages:1,query:'',pageSize:20,owner});$('users-query').value='';$('users-page-size').value='20';}
  const request=++usersList.request;
  $('users-prev').disabled=$('users-next').disabled=true;
  $('users-table').replaceChildren();
  $('users-summary').textContent='加载中…';
  try{
    const params=new URLSearchParams({q:usersList.query,page:usersList.page,page_size:usersList.pageSize});
    const data=await api('/api/users?'+params);
    if(state.csrf!==owner||request!==usersList.request||!state.user?.can_manage_users)return;
    usersList.page=data.page;usersList.pages=data.pages;
    $('users-table').replaceChildren(...data.items.map(user=>node('tr',{},[node('td',{text:user.username}),node('td',{text:user.email||'未绑定'}),node('td',{text:user.is_admin?'管理员':'成员'}),node('td',{text:user.is_admin?'不限':user.daily_limit+' 次'}),node('td',{},[node('span',{class:'pill',text:user.enabled?'正常':'已停用'})]),node('td',{class:'user-actions'},[node('button',{class:'text-button',text:'编辑',onclick:()=>userEditor(user)}),...(String(user.id)!==String(state.user.id)&&user.username!=='admin'?[node('button',{class:'text-button danger-text',text:'删除',onclick:()=>confirmDeleteUser(user)})]:[])])])));
    if(!data.items.length)$('users-table').append(node('tr',{},[node('td',{colspan:'6',class:'users-empty',text:usersList.query?'没有找到匹配的账号':'暂无用户'})]));
    $('users-summary').textContent='共 '+data.total+' 个用户';
    $('users-page').textContent=data.page+' / '+data.pages;
    $('users-prev').disabled=data.page<=1;
    $('users-next').disabled=data.page>=data.pages;
  }catch(error){if(state.csrf===owner&&request===usersList.request){$('users-summary').textContent='加载失败，请重新搜索';toast(message(error));}}
}
$('users-search-form').addEventListener('submit',event=>{event.preventDefault();usersList.query=$('users-query').value.trim();usersList.page=1;loadUsers();});
$('users-query').addEventListener('input',()=>{if(!$('users-query').value&&usersList.query){usersList.query='';usersList.page=1;loadUsers();}});
$('users-page-size').addEventListener('change',()=>{usersList.pageSize=Number($('users-page-size').value);usersList.page=1;loadUsers();});
$('users-prev').addEventListener('click',()=>{if(usersList.page>1){usersList.page--;loadUsers();}});
$('users-next').addEventListener('click',()=>{if(usersList.page<usersList.pages){usersList.page++;loadUsers();}});
function userEditor(user=null){
  const form=node('form'),username=node('input',{name:'username',maxlength:'64',required:'',value:user?.username||'',...(user?{readonly:''}:{})}),password=node('input',{name:'password',type:'password',minlength:'12',maxlength:'256',autocomplete:'new-password',...(!user?{required:''}:{placeholder:'留空保留当前密码'})}),limit=node('input',{name:'daily_limit',type:'number',min:'0',max:'10000',value:user?.daily_limit??5,required:''}),admin=node('input',{name:'is_admin',type:'checkbox',checked:!!user?.is_admin}),enabled=node('input',{name:'enabled',type:'checkbox',checked:user?!!user.enabled:true});
  form.append(field('账号',username),field(user?'重置密码':'密码',password),field('每日搜索额度',limit),node('label',{class:'toggle-row'},[node('span',{text:'管理员权限（不限搜索次数）'}),admin]));if(user)form.append(node('label',{class:'toggle-row'},[node('span',{text:'启用账号'}),enabled]));
  const syncLimit=()=>{limit.disabled=admin.checked;limit.closest('label').hidden=admin.checked;};admin.addEventListener('change',syncLimit);syncLimit();
  form.append(node('div',{class:'form-actions'},[node('button',{type:'button',class:'secondary',text:'取消',onclick:closeModal}),node('button',{type:'submit',class:'primary',text:user?'保存修改':'创建用户'})]));
  form.addEventListener('submit',async(event)=>{event.preventDefault();try{await api('/api/users',{method:user?'PATCH':'POST',body:JSON.stringify({username:username.value,password:password.value,daily_limit:Number(limit.value),is_admin:admin.checked,enabled:enabled.checked})});closeModal();loadUsers();toast(user?'账号已更新':'账号已创建');}catch(error){toast(message(error));}});openModal(user?'编辑账号':'创建用户',form);
}
$('add-user').addEventListener('click',()=>userEditor());

function confirmDeleteUser(user){
  const form=node('form'),confirm=node('input',{required:'',autocomplete:'off',maxlength:'64',placeholder:'输入账号名确认', 'aria-label':'输入账号名确认'}),submit=node('button',{type:'submit',class:'primary',text:'删除账号',disabled:true}),owner=state.csrf;
  form.append(node('p',{text:'删除账号“'+user.username+'”及其登录、授权、绑定和搜索记录？此操作无法恢复。'}),confirm,node('div',{class:'form-actions'},[node('button',{type:'button',class:'secondary',text:'取消',onclick:closeModal}),submit]));
  confirm.addEventListener('input',()=>submit.disabled=confirm.value!==user.username);
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(confirm.value!==user.username||state.csrf!==owner)return;submit.disabled=true;
    try{
      await api('/api/users/'+encodeURIComponent(user.id),{method:'DELETE',body:JSON.stringify({username:confirm.value})});
      if(state.csrf!==owner)return;closeModal();await loadUsers();toast('账号已删除');
    }catch(error){if(state.csrf===owner){toast(message(error));submit.disabled=confirm.value!==user.username;}}
  });
  openModal('删除账号',form);
}
