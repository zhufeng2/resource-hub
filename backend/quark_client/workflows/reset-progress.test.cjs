'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {resetFolderProgress}=require('./reset-progress.cjs');
function fixture(t,count=2){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rh-reset-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const files={series:{fid:'series',file_name:'My series',file_type:0,pdir_fid:'0'},season:{fid:'season',file_name:'Season1',file_type:0,pdir_fid:'series'},
  note:{fid:'note',file_name:'Guide.txt',file_type:1,format_type:'text/plain',pdir_fid:'series'}};
 for(let i=0;i<count;i++)files['v'+i]={fid:'v'+i,file_name:i+'.mp4',file_type:1,format_type:'video/mp4',duration:100,pdir_fid:i===0?'series':'season',last_play_info:{time:20}};
 const reports=[];
 const client={files:{getInfo:async fid=>structuredClone(files[fid])},folders:{readChildren:async fid=>Object.values(files).filter(f=>f.pdir_fid===fid).map(f=>structuredClone(f))},
  playback:{setPosition:async a=>{reports.push(a);files[a.fid].last_play_info={time:a.seconds};return {code:0};},getProgress:async fid=>({fid,positionSeconds:files[fid].last_play_info?.time??null})}};
 return {client,files,reports,journal:path.join(dir,'op.json'),args:{folderFid:'series',folderName:'My series',includeSubfolders:true,explicitReset:true},options:{sleep:async()=>{}}};
}
test('requires an explicit named folder and explicit reset instruction; root is forbidden',async t=>{
 const f=fixture(t);
 assert.equal((await resetFolderProgress(f.client,{...f.args,folderFid:'0'},f.journal,true,f.options)).error,'explicit_folder_required');
 assert.equal((await resetFolderProgress(f.client,{...f.args,explicitReset:false},f.journal,true,f.options)).error,'explicit_reset_required');
 assert.equal((await resetFolderProgress(f.client,{...f.args,folderName:'Wrong folder'},f.journal,true,f.options)).error,'scope_mismatch');
 assert.equal(f.reports.length,0);
});
test('preview enumerates only the selected folder, includes subfolders when requested, never writes',async t=>{
 const f=fixture(t);
 const preview=await resetFolderProgress(f.client,f.args,f.journal,false,f.options);
 assert.equal(preview.phase,'preview');assert.equal(preview.total,2);
 const direct=await resetFolderProgress(f.client,{...f.args,includeSubfolders:false},f.journal,false,f.options);
 assert.equal(direct.total,1);assert.equal(f.reports.length,0);assert.equal(fs.existsSync(f.journal),false);
});
test('one report per video followed by independent readbacks, existing zero is not reported again',async t=>{
 const f=fixture(t);f.files.v1.last_play_info.time=0;
 const result=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(result.phase,'verified');assert.equal(result.verified,2);
 assert.deepEqual(f.reports,[{fid:'v0',seconds:0}]);
 assert.equal((await resetFolderProgress(f.client,f.args,f.journal,true,f.options)).phase,'verified');
 assert.equal(f.reports.length,1);
});
test('lost acknowledgement resumes readback without a second reset report',async t=>{
 const f=fixture(t,1);const original=f.client.playback.setPosition;
 f.client.playback.setPosition=async a=>{await original(a);throw new Error('lost acknowledgement');};
 await assert.rejects(resetFolderProgress(f.client,f.args,f.journal,true,f.options));
 assert.equal((await resetFolderProgress(f.client,f.args,f.journal,true,f.options)).phase,'verified');
 assert.equal(f.reports.length,1);
});
test('delayed progress readback is not treated as reset success, and does not trigger duplicate reports',async t=>{
 const f=fixture(t,1);let visible=false;
 f.client.playback.getProgress=async()=>({positionSeconds:visible?0:20});
 const pending=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(pending.phase,'in_progress');assert.equal(pending.verified,0);
 visible=true;
 assert.equal((await resetFolderProgress(f.client,f.args,f.journal,true,f.options)).phase,'verified');
 assert.equal(f.reports.length,1);
});
test('large series uses bounded parallel workers and handles more than five videos',async t=>{
 const f=fixture(t,120);
 const first=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(first.phase,'in_progress');assert.equal(first.verified,100);
 const second=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(second.phase,'verified');assert.equal(second.verified,120);assert.equal(f.reports.length,120);
});
test('a file moved outside the selected folder is not reset during continuation',async t=>{
 const f=fixture(t,6);f.options.maxItems=5;await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 f.files.v5.pdir_fid='outside';f.files.outside={fid:'outside',file_name:'Other',file_type:0,pdir_fid:'0'};
 const result=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(result.phase,'scope_changed');assert.equal(f.reports.length,5);
});
test('unknown duration is reported as partial rather than claiming all videos reset',async t=>{
 const f=fixture(t,1);delete f.files.v0.duration;
 const result=await resetFolderProgress(f.client,f.args,f.journal,true,f.options);
 assert.equal(result.phase,'partial');assert.equal(result.skipped,1);assert.equal(f.reports.length,0);
});

test('parallel failures drain workers before releasing the operation lock and never duplicate reports',async t=>{
 const f=fixture(t,8);let active=0,max=0;
 const original=f.client.playback.setPosition;
 f.client.playback.setPosition=async a=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,5));active--;await original(a);if(a.fid==='v0')throw new Error('ack lost');};
 await assert.rejects(resetFolderProgress(f.client,f.args,f.journal,true,f.options));
 assert.equal(active,0);assert.ok(max<=3);assert.ok(max>1);
 f.client.playback.setPosition=original;
 assert.equal((await resetFolderProgress(f.client,f.args,f.journal,true,f.options)).phase,'verified');
 assert.equal(new Set(f.reports.map(r=>r.fid)).size,f.reports.length);
});
