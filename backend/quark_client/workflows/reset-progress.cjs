'use strict';
const fs = require('node:fs');
const {id} = require('../validation.cjs');
const {fileSummary, progressSummary} = require('../output.cjs');
const {writeJournal: persist} = require('../journal.cjs');

const isVideo = f => f.file_type === 1 && (/^video\//i.test(f.format_type || '') || /\.(mp4|mkv|avi|mov|m4v|webm|ts|m2ts|rmvb|flv|wmv)$/i.test(f.file_name || ''));
function resetSummary(r) {
  const verified = r.items.filter(i => i.state === 'verified').length;
  const skipped = r.items.filter(i => i.state === 'skipped').length;
  return {phase:r.phase, folder:r.folder, include_subfolders:r.plan.includeSubfolders,
    total:r.items.length, verified, skipped, remaining:r.items.length-verified-skipped,
    results:r.items.filter(i => i.state !== 'queued').slice(0,30).map(i => ({fid:i.fid,name:i.name,state:i.state,reason:i.reason,after_seconds:i.afterSeconds})),
    message:r.phase==='verified'?'指定范围的视频进度已回读确认为0。':'复用原参数和原请求编号接续；不会重复上报已提交条目。'};
}
async function inventory(client, folder, recursive) {
  const queue=[folder.fid], seen=new Set(), videos=new Map(); let total=0;
  while(queue.length) {
    const parent=queue.shift();
    if(seen.has(parent))throw new Error('directory_cycle');
    seen.add(parent); if(seen.size>200)throw new Error('folder_limit');
    const children=await client.folders.readChildren(parent);
    total+=children.length; if(total>10000)throw new Error('entry_limit');
    for(const f of children) {
      if(String(f.pdir_fid)!==String(parent))throw new Error('directory_mapping_mismatch');
      if(f.file_type===0&&recursive)queue.push(String(f.fid));
      else if(isVideo(f))videos.set(String(f.fid),{fid:String(f.fid),name:f.file_name,state:'queued'});
    }
    if(videos.size>2000)throw new Error('video_limit');
  }
  return [...videos.values()];
}
async function checkScope(client, file, root, deadline) {
  let current=String(file.pdir_fid); const seen=new Set();
  while(current!==root) {
    if(Date.now()>deadline)throw new Error('work_budget');
    if(current==='0'||seen.has(current)||seen.size>=64)throw new Error('file_outside_scope');
    seen.add(current); const parent=await client.files.getInfo(current);
    if(parent.file_type!==0)throw new Error('invalid_parent');
    current=String(parent.pdir_fid);
  }
}

async function resetFolderProgress(client,a,journal,execute=false,{sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}) {
  id(a.folderFid);id(a.folderName,'folderName');
  if(a.folderFid==='0')return {error:'explicit_folder_required',message:'必须明确指定某个文件夹，不能重置全盘。'};
  if(execute&&a.explicitReset!==true)return {error:'explicit_reset_required',message:'只有用户明确要求把指定文件夹的观看进度全部归零，才可执行。'};
  const plan={folderFid:a.folderFid,folderName:a.folderName,includeSubfolders:a.includeSubfolders!==false};
  const deadline=Date.now()+20000;
  const folder=await client.files.getInfo(a.folderFid);
  if(folder.file_type!==0||folder.file_name!==a.folderName)return {error:'scope_mismatch',message:'实际文件夹与指定名称不一致，未执行重置。'};
  let r;
  if(fs.existsSync(journal)) {
    r=JSON.parse(fs.readFileSync(journal,'utf8'));
    if(r.kind!=='reset_progress'||JSON.stringify(r.plan)!==JSON.stringify(plan))throw new Error('plan_conflict');
    if(r.phase==='verified')return resetSummary(r);
  } else {
    const items=await inventory(client,folder,plan.includeSubfolders);
    r={kind:'reset_progress',phase:'ready',plan,folder:fileSummary(folder),items};
    if(!execute)return {...resetSummary(r),phase:'preview',message:'仅预览指定文件夹的视频范围，未修改观看进度。',files:items.slice(0,30).map(({fid,name})=>({fid,name}))};
    persist(journal,r,true);
  }
  if(!execute)return resetSummary(r);
  // A bounded slice keeps a large series resumable within the MCP request timeout.
  let processed=0;
  for(const item of r.items) {
    if(['verified','skipped'].includes(item.state))continue;
    if(++processed>5||Date.now()>deadline)break;
    const file=await client.files.getInfo(item.fid);
    if(!isVideo(file)||file.file_name!==item.name){r.phase='scope_changed';persist(journal,r);return resetSummary(r);}
    try{await checkScope(client,file,a.folderFid,deadline);}
    catch(error){if(error.message==='work_budget')break;r.phase='scope_changed';persist(journal,r);return resetSummary(r);}
    if(!plan.includeSubfolders&&String(file.pdir_fid)!==a.folderFid){r.phase='scope_changed';persist(journal,r);return resetSummary(r);}
    if(item.state==='queued') {
      const before=progressSummary(file);
      if(typeof before.durationSeconds!=='number'||before.durationSeconds<=0){
        item.state='skipped';item.reason='invalid_duration';persist(journal,r);continue;
      }
      if(before.positionSeconds===0){item.state='verified';item.afterSeconds=0;persist(journal,r);continue;}
      if(Date.now()>deadline)break;
      item.beforeSeconds=before.positionSeconds;item.state='submitting';r.phase='in_progress';persist(journal,r);
      // Same interface as research/examples/set-progress.cjs: one report, then readbacks.
      await client.playback.setPosition({fid:item.fid,seconds:0});
      item.state='submitted';persist(journal,r);
    }
    // A lost acknowledgement leaves submitting: only read back, never report again.
    for(let attempt=0;attempt<4&&Date.now()<deadline;attempt++) {
      await sleep(attempt===0?1000:2000);
      const after=await client.playback.getProgress(item.fid);
      item.afterSeconds=after.positionSeconds;item.readbackAttempts=(item.readbackAttempts||0)+1;
      if(after.positionSeconds===0){item.state='verified';persist(journal,r);break;}
      persist(journal,r);
    }
  }
  const pending=r.items.some(i=>!['verified','skipped'].includes(i.state));
  r.phase=pending?'in_progress':r.items.some(i=>i.state==='skipped')?'partial':'verified';
  persist(journal,r);return resetSummary(r);
}
module.exports={resetFolderProgress,resetSummary};
