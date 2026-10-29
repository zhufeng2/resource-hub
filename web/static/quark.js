'use strict';
let quarkVersion=0,quarkRevealed=false,quarkBound=false,quarkRevealPending=false;
function syncQuarkCookie(){
  const value=$('quark-cookie').value;
  $('toggle-quark-cookie').disabled=$('copy-quark-cookie').disabled=quarkRevealPending||(!value&&!quarkBound);
  if(!value)quarkRevealed=false;
  $('quark-cookie').type=quarkRevealed?'text':'password';
  $('toggle-quark-cookie').textContent=quarkRevealed?'隐藏':'显示';
  $('toggle-quark-cookie').setAttribute('aria-pressed',String(quarkRevealed));
}
function resetQuarkAccount(){
  quarkVersion++;quarkRevealed=false;quarkBound=false;quarkRevealPending=false;$('quark-form').reset();$('quark-unbind').disabled=true;
  $('quark-cookie').placeholder='请输入 Cookie';$('quark-cookie').setAttribute('aria-label','Cookie');
  syncQuarkCookie();$('quark-status').textContent='未绑定';
}
// Load the owner's saved value into a password input, just like the Token row.
// Do not use decorative dots as a placeholder for a value that is not loaded.
function renderQuarkAccount(data,clear=false){
  const bound=!!data.bound;
  if(!bound&&quarkBound)clear=true;
  quarkBound=bound;
  if(clear){quarkRevealed=false;$('quark-cookie').value='';}
  $('quark-cookie').placeholder=bound&&!$('quark-cookie').value?'正在读取 Cookie…':'请输入 Cookie';
  $('quark-cookie').setAttribute('aria-label',bound?'Cookie（已保存，输入可更新）':'Cookie');
  $('quark-unbind').disabled=!bound;
  $('quark-status').textContent=bound?'已绑定':'未绑定';
  syncQuarkCookie();
}
async function loadQuarkAccount(){
  if(!state.user)return;const owner=state.csrf,version=++quarkVersion;
  // A newer load invalidates any previous reveal request, including its busy flag.
  quarkRevealPending=false;
  try{
    const data=await api('/api/quark-account');
    if(state.csrf!==owner||version!==quarkVersion)return;
    renderQuarkAccount(data);
    if(data.bound&&!$('quark-cookie').value)await readQuarkCookie();
  }catch(error){if(state.csrf===owner&&version===quarkVersion){
    $('quark-status').textContent=message(error);
    if(quarkBound&&!$('quark-cookie').value)$('quark-cookie').placeholder='Cookie 读取失败';
  }}
}
$('quark-cookie').addEventListener('input',syncQuarkCookie);
async function readQuarkCookie(){
  if($('quark-cookie').value)return $('quark-cookie').value;
  if(!quarkBound||quarkRevealPending)return '';
  const owner=state.csrf,version=quarkVersion;
  quarkRevealPending=true;syncQuarkCookie();
  try{
    const data=await post('/api/quark-account/reveal');
    if(!state.user||state.csrf!==owner||quarkVersion!==version)return '';
    if(typeof data.cookie!=='string'||!data.cookie)throw new Error('无法读取已保存的 Cookie');
    if(!$('quark-cookie').value)$('quark-cookie').value=data.cookie;
    $('quark-cookie').placeholder='请输入 Cookie';
    return $('quark-cookie').value;
  }finally{if(state.csrf===owner&&quarkVersion===version){quarkRevealPending=false;syncQuarkCookie();}}
}
$('toggle-quark-cookie').addEventListener('click',async()=>{
  try{if(!await readQuarkCookie())return;quarkRevealed=!quarkRevealed;syncQuarkCookie();}
  catch(error){toast(message(error));}
});
$('copy-quark-cookie').addEventListener('click',async()=>{
  try{const value=await readQuarkCookie();if(value)clipboard(value);}catch(error){toast(message(error));}
});
$('quark-form').addEventListener('submit',async event=>{
  event.preventDefault();const owner=state.csrf,version=++quarkVersion,button=event.currentTarget.querySelector('[type=submit]');
  button.disabled=true;
  const cookie=$('quark-cookie').value;
  try{const data=await post('/api/quark-account',{cookie});
    if(state.user&&state.csrf===owner&&version===quarkVersion){renderQuarkAccount(data);toast('夸克账号已绑定');}}
  catch(error){if(state.csrf===owner&&version===quarkVersion)toast(message(error));}
  finally{button.disabled=false;}
});
$('quark-unbind').addEventListener('click',async()=>{
  const owner=state.csrf,version=++quarkVersion;
  try{const data=await api('/api/quark-account',{method:'DELETE'});
    if(state.user&&state.csrf===owner&&version===quarkVersion){renderQuarkAccount(data,true);toast('已解除夸克绑定');}}
  catch(error){if(state.csrf===owner&&version===quarkVersion)toast(message(error));}
});
