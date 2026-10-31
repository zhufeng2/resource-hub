'use strict';
(() => {
  function setMode(form, registering){
    (form.closest('.login-card')?$('login-title-panel'):$('login-title')).textContent=registering?'注册账号':'登录后继续';
    form.dataset.mode=registering?'register':'login';
    form.querySelector('[data-registration-fields]').hidden=!registering;
    form.querySelectorAll('[data-registration-fields] input').forEach(input=>input.disabled=!registering);
    form.querySelector('[name=password]').autocomplete=registering?'new-password':'current-password';
    form.querySelector('[name=password]').minLength=registering?12:0;
    form.querySelector('button[type=submit]').textContent=registering?'注册':'登录';
    form.querySelector('[data-auth-toggle]').textContent=registering?'已有账号，去登录':'注册账号';
    form.querySelector('.form-error').textContent='';
  }
  function countdown(button){
    const original=button.textContent;
    const deadline=Date.now()+60000;
    button.disabled=true;
    const tick=()=>{
      const remaining=Math.ceil((deadline-Date.now())/1000);
      if(remaining<=0){button.textContent=original;button.disabled=false;return;}
      button.textContent=remaining+' 秒后重发';setTimeout(tick,1000);
    };
    tick();
  }
  async function sendCode(form, button, binding=false){
    const input=form.querySelector('[name=email]');
    if(!input.reportValidity())return;
    button.disabled=true;
    try{
      const result=await post(binding?'/api/email/code':'/api/register/code',{email:input.value});
      countdown(button);toast(result.message);
    }catch(error){button.disabled=false;toast(message(error));}
  }
  function sync(){
    loginForms.forEach(form=>{
      form.querySelector('[data-auth-toggle]').hidden=!state.registrationEnabled;
      if(!state.registrationEnabled)setMode(form,false);
    });
  }
  function syncEmail(){
    const user=state.user, bound=!!user?.email, enabled=!!user?.email_binding_enabled;
    const form=$('email-binding-form');
    $('account-email').value=user?.email||'';
    $('account-email').readOnly=bound;
    $('account-email').disabled=!bound&&!enabled;
    $('email-binding-code-label').hidden=bound||!enabled;
    form.querySelector('[name=code]').disabled=bound||!enabled;
    $('email-binding-actions').hidden=bound||!enabled;
    $('email-binding-status').textContent=bound?'已验证':enabled?'':'邮件服务暂未配置';
  }
  loginForms.forEach(form=>{
    form.querySelector('[data-auth-toggle]').addEventListener('click',()=>setMode(form,form.dataset.mode!=='register'));
    const button=form.querySelector('[data-send-code]');
    button.addEventListener('click',()=>sendCode(form,button));
  });
  $('send-binding-code').addEventListener('click',()=>sendCode($('email-binding-form'),$('send-binding-code'),true));
  $('email-binding-form').addEventListener('submit',async event=>{
    event.preventDefault();
    const form=event.currentTarget, button=form.querySelector('[type=submit]'), owner=state.csrf;
    button.disabled=true;
    try{
      const result=await post('/api/email',Object.fromEntries(new FormData(form)));
      if(state.csrf!==owner||!state.user)return;
      state.user.email=result.email;form.querySelector('[name=code]').value='';syncEmail();toast('邮箱已绑定');
    }catch(error){toast(message(error));}finally{button.disabled=false;}
  });
  window.ResourceRegistration={sync,syncEmail,setMode};sync();syncEmail();
})();
