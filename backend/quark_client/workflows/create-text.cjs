'use strict';
const fs=require('node:fs');
const {createHash}=require('node:crypto');
const {filename,id}=require('../validation.cjs');
const {fileSummary}=require('../output.cjs');
const {writeJournal:persist}=require('../journal.cjs');
const {uploadText,readTextBack}=require('../text-upload.cjs');

async function createText(client,a,journal,execute=false,{upload=uploadText,readBack=readTextBack}={}) {
  id(a.parentFid);filename(a.name);
  if(!/\.(txt|md)$/i.test(a.name)||typeof a.content!=='string'||
    /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(a.content))throw new Error('invalid_text_file');
  const bytes=Buffer.from(a.content,'utf8');
  if(bytes.length===0||bytes.length>32768)throw new Error('text_size_limit');
  const sha1=createHash('sha1').update(bytes).digest('hex');
  const md5=createHash('md5').update(bytes).digest('hex');
  const plan={parentFid:a.parentFid,name:a.name,size:bytes.length,
    sha256:createHash('sha256').update(bytes).digest('hex')};
  let r;
  if(fs.existsSync(journal)) {
    r=JSON.parse(fs.readFileSync(journal,'utf8'));
    if(r.kind!=='text'||JSON.stringify(r.plan)!==JSON.stringify(plan))throw new Error('plan_conflict');
    if(r.phase==='verified')return {phase:r.phase,file:r.savedFile,content_verified:true};
  } else {
    if(a.parentFid!=='0') {
      const parent=await client.files.getInfo(a.parentFid);
      if(parent.file_type!==0)throw new Error('invalid_parent');
    }
    const children=await client.folders.readChildren(a.parentFid);
    if(children.some(f=>f.file_name===a.name))return {error:'name_exists',message:'已有同名条目，不覆盖。'};
    if(!execute)return {phase:'preview',parent:a.parentFid,name:a.name,size:bytes.length};
    r={kind:'text',phase:'submitting',plan,destination:a.parentFid};
    // Persist only the content digest, never the text or OSS credentials.
    persist(journal,r,true);
    const now=Date.now();
    const result=await client.transport.call('files.uploadPre',{body:{
      ccp_hash_update:false,parallel_upload:false,dir_name:'',format_type:'text/plain',sha1,md5,pdir_fid:a.parentFid,size:bytes.length,file_name:a.name,l_updated_at:now,l_created_at:now}});
    const pre=result.data;
    if(!pre||typeof pre!=='object')throw new Error('invalid_upload_pre');
    if(pre.finish!==true)await upload(client,pre,bytes);
    r.phase='submitted';persist(journal,r);
  }
  // A previous ambiguous submission is only read back, never uploaded again.
  const matches=(await client.folders.readChildren(a.parentFid)).filter(f=>f.file_name===a.name);
  if(matches.length===1) {
    const file=await client.files.getInfo(matches[0].fid);
    if(file.file_type===1&&String(file.pdir_fid)===a.parentFid&&file.file_name===a.name&&Number(file.size)===bytes.length&&
       bytes.equals(await readBack(client,String(file.fid)))) {
      r.savedFile=fileSummary(file);r.phase='verified';persist(journal,r);
      return {phase:r.phase,file:r.savedFile,content_verified:true};
    }
  }
  return {phase:r.phase,content_verified:false,message:'尚未核验文件内容；用原参数和原编号续查，不重复上传。'};
}
module.exports={createText};
