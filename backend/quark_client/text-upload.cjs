'use strict';
const https = require('node:https');
const dns = require('node:dns');

// Only the OSS host returned by Quark may receive the short-lived upload authorization.
// Never send the account Cookie, follow redirects or accept user-supplied URLs.
function uploadUrl(value) {
  const url = new URL(value);
  if(url.protocol!=='https:' || url.username || url.password || url.port || url.hash ||
    !(/^[a-z0-9][a-z0-9-]*\.oss-cn-[a-z0-9-]+\.aliyuncs\.com$/.test(url.hostname)||/^(?:[a-z0-9][a-z0-9-]*\.)?pds\.quark\.cn$/.test(url.hostname)))
    throw new Error('unsupported_upload_host');
  return url;
}
function publicLookup(host, options, callback) {
  dns.lookup(host,{family:4,all:true},(error,addresses)=>{
    if(error)return callback(new Error('upload_dns_failed'));
    const safe=addresses.length && addresses.every(({address})=>{
      const [a,b]=address.split('.').map(Number);
      return a>0 && a<224 && a!==10 && a!==127 && !(a===100&&b>=64&&b<=127) &&
        !(a===169&&b===254) && !(a===172&&b>=16&&b<=31) && !(a===192&&[0,168].includes(b)) &&
        !(a===198&&[18,19,51].includes(b)) && !(a===203&&b===0);
    });
    if(!safe)return callback(new Error('upload_dns_rejected'));
    return options?.all ? callback(null,addresses) : callback(null,addresses[0].address,4);
  });
}
// Each authorization covers exactly one OSS request; Cookie goes only to Quark.
async function uploadText(client, pre, bytes, {request=requestOss}={}) {
  if(typeof pre.bucket!=='string'||typeof pre.obj_key!=='string'||typeof pre.upload_id!=='string' ||
     typeof pre.task_id!=='string'||typeof pre.auth_info!=='string')throw new Error('invalid_upload_pre');
  // The official client upgrades the endpoint to HTTPS before constructing OSS requests.
  const base=uploadUrl(String(pre.upload_url).replace(/^http:/,'https:'));
  if(!/^[a-z0-9][a-z0-9-]{1,62}$/.test(pre.bucket)||base.search)throw new Error('invalid_upload_bucket');
  if(base.hostname==='pds.quark.cn')base.hostname=pre.bucket+'.'+base.hostname;
  if(!base.hostname.startsWith(pre.bucket+'.'))throw new Error('invalid_upload_bucket');
  const objectUrl=new URL('/'+pre.obj_key.split('/').map(encodeURIComponent).join('/'),base);
  const resource='/'+pre.bucket+'/'+pre.obj_key;
  async function signed(method, query, content, mime, extra={}) {
    const headers={'Content-Type':mime,'Content-Length':content.length,'x-oss-date':new Date().toUTCString(),...extra};
    headers['Content-MD5']=require('node:crypto').createHash('md5').update(content).digest('base64');
    const names=Object.keys(query).sort();
    const canonicalResource=resource+(names.length?'?'+names.map(k=>k+'='+query[k]).join('&'):'');
    const meta=[method,headers['Content-MD5'],mime,headers['x-oss-date'],
      ...Object.keys(headers).filter(k=>k.startsWith('x-oss-')).sort().map(k=>k+':'+headers[k].trim()),canonicalResource].join('\n');
    const result=await client.transport.call('files.uploadAuth',{body:{task_id:pre.task_id,auth_info:pre.auth_info,auth_meta:meta}});
    if(typeof result.data?.auth_key!=='string')throw new Error('invalid_upload_auth');
    headers.Authorization=result.data.auth_key;
    const url=new URL(objectUrl);url.search=new URLSearchParams(query).toString();
    return request(url,method,headers,content);
  }
  const part=await signed('PUT',{partNumber:'1',uploadId:pre.upload_id},bytes,'text/plain');
  const etag=part.headers.etag;
  if(typeof etag!=='string'||!/^"?[a-fA-F0-9]{32}"?$/.test(etag))throw new Error('invalid_upload_etag');
  const xml=Buffer.from('<?xml version="1.0" encoding="UTF-8"?>\n<CompleteMultipartUpload>\n<Part>\n<PartNumber>1</PartNumber>\n<ETag>'+etag+'</ETag>\n</Part>\n</CompleteMultipartUpload>');
  const extra={};
  if(pre.callback) {
    if(typeof pre.callback.callbackUrl!=='string'||typeof pre.callback.callbackBody!=='string')throw new Error('invalid_upload_callback');
    extra['x-oss-callback']=Buffer.from(JSON.stringify({callbackUrl:encodeURI(pre.callback.callbackUrl),callbackBody:pre.callback.callbackBody})).toString('base64');
  }
  await signed('POST',{uploadId:pre.upload_id},xml,'application/xml',extra);
  await client.transport.call('files.uploadFinish',{body:{obj_key:pre.obj_key,task_id:pre.task_id}});
}
function requestOss(url,method,headers,payload,requestImpl=https.request) {
  uploadUrl(url);
  return requestBytes(url,method,headers,payload,1048576,requestImpl);
}
async function readTextBack(client,fid,{request=requestBytes}={}) {
  const result=await client.transport.call('files.downloadInfo',{body:{fids:[fid]}});
  const file=Array.isArray(result.data)?result.data.find(f=>String(f.fid)===fid):null;
  const url=new URL(file?.download_url);
  if(url.protocol!=='https:'||url.username||url.password||url.port||url.hash||
     !/^dl-pc-[a-z0-9-]+\.pds\.quark\.cn$/.test(url.hostname))throw new Error('unsupported_download_host');
  const jar=client.transport.cookies.get(require('./endpoints.cjs').PC);
  const Cookie=[...jar].map(([k,v])=>k+'='+v).join('; ');
  // Quark's own download CDN requires the bound account Cookie. No Cookie is
  // ever sent to OSS, and neither CDN URLs nor downloaded content are returned.
  const response=await request(url,'GET',{'User-Agent':'Mozilla/5.0',
    Referer:'https://pan.quark.cn/',Cookie},undefined,32768);
  return response.body;
}
function requestBytes(url,method,headers,payload,limit,requestImpl=https.request) {
  return new Promise((resolve,reject)=>{
    let req,timer,done=false;
    const finish=(error,value)=>{if(done)return;done=true;clearTimeout(timer);error?reject(new Error(error)):resolve(value);};
    try {
      req=requestImpl(url,{method,lookup:publicLookup,headers},res=>{
        let size=0;const chunks=[];
        res.on('data',chunk=>{size+=chunk.length;if(size>limit){finish('upload_response_limit');res.destroy();}else chunks.push(chunk);});
        res.on('error',()=>finish('upload_response_failed'));
        res.on('aborted',()=>finish('upload_response_failed'));
        res.on('end',()=>{
          if(res.statusCode!==200)return finish('upload_not_confirmed');
          finish(null,{headers:res.headers,body:Buffer.concat(chunks)});
        });
      });
      req.on('error',()=>finish('upload_connection_failed'));
      timer=setTimeout(()=>{finish('upload_timeout');req.destroy();},10000);
      req.end(payload);
    } catch {finish('upload_failed');}
  });
}
module.exports={uploadText,uploadUrl,requestOss,readTextBack};
