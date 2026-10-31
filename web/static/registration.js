'use strict';
(() => {
  const recoveryReady=()=>!!state.passwordResetEnabled;
  function setMode(form, mode){
    mode=mode===true?'register':mode===false?'login':mode;
    const registering=mode==='register',resetting=mode==='reset',emailMode=registering||resetting;
    const surface=form.closest('.login-card,.login-dialog');
    (form.closest('.login-card')?$('login-title-panel'):$('login-title')).textContent=resetting?'找回密码':registering?'注册账号':'登录后继续';
    surface.querySelector('.muted').textContent=resetting?'验证邮箱，设置新密码':registering?'验证邮箱后创建账号':'使用你的账号开始搜索';
    form.dataset.mode=mode;
    form.querySelector('[data-username-fields]').hidden=resetting;
    form.querySelector('[name=username]').disabled=resetting;
    form.querySelector('[data-registration-fields]').hidden=!emailMode;
    form.querySelectorAll('[data-registration-fields] input').forEach(input=>input.disabled=!emailMode);
    const password=form.querySelector('[name=password]');
    password.autocomplete=emailMode?'new-password':'current-password';password.minLength=emailMode?12:0;
    form.querySelector('[data-password-fields] label').textContent=resetting?'新密码':'密码';
    form.querySelector('[data-confirm-password]').hidden=!resetting;
    form.querySelector('[name=confirm]').disabled=!resetting;
    password.value='';form.querySelector('[name=confirm]').value='';form.querySelector('[name=code]').value='';
    form.querySelector('button[type=submit]').textContent=resetting?'重置密码':registering?'注册':'登录';
    form.querySelector('button[type=submit]').disabled=resetting&&!recoveryReady();
    form.querySelector('[data-auth-toggle]').textContent=registering?'已有账号，去登录':'注册账号';
    form.querySelector('[data-auth-toggle]').hidden=resetting||!state.registrationEnabled;
    form.querySelector('[data-reset-toggle]').textContent=resetting?'返回登录':'忘记密码';
    form.querySelector('[data-reset-toggle]').hidden=registering;
    surface.querySelector('[data-auth-help]').textContent=resetting?(recoveryReady()?'无验证邮箱的测试账号请联系管理员':'邮箱找回暂不可用，请联系管理员'):'需要帮助？请联系管理员';
    const send=form.querySelector('[data-send-code]');
    send.disabled=!!send.dataset.cooldown||(resetting&&!recoveryReady());
    form.querySelector('.form-error').textContent='';
  }
  function countdown(button,form){
    const deadline=Date.now()+60000;button.dataset.cooldown='true';button.disabled=true;
    const tick=()=>{
      const remaining=Math.ceil((deadline-Date.now())/1000);
      if(remaining<=0){delete button.dataset.cooldown;button.textContent='获取验证码';button.disabled=form.dataset.mode==='reset'&&!recoveryReady();return;}
      button.textContent=remaining+' 秒后重发';setTimeout(tick,1000);
    };
    tick();
  }
  async function sendCode(form, button){
    const input=form.querySelector('[name=email]');
    if(!input.reportValidity())return;
    const mode=form.dataset.mode;
    button.disabled=true;
    try{
      const result=await post(mode==='reset'?'/api/password/reset/code':'/api/register/code',{email:input.value});
      countdown(button,form);toast(result.message);
    }catch(error){button.disabled=false;toast(message(error));}
  }
  function sync(){
    loginForms.forEach(form=>{
      if(!state.registrationEnabled&&form.dataset.mode==='register')setMode(form,false);
      form.querySelector('[data-auth-toggle]').hidden=form.dataset.mode==='reset'||!state.registrationEnabled;
    });
  }
  loginForms.forEach(form=>{
    form.querySelector('[data-auth-toggle]').addEventListener('click',()=>setMode(form,form.dataset.mode==='register'?'login':'register'));
    form.querySelector('[data-reset-toggle]').addEventListener('click',()=>setMode(form,form.dataset.mode==='reset'?'login':'reset'));
    const button=form.querySelector('[data-send-code]');
    button.addEventListener('click',()=>sendCode(form,button));
  });
  window.ResourceRegistration={sync,setMode};sync();
})();
