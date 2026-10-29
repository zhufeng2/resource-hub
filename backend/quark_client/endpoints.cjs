'use strict';

// 所有路径都来自已有前端分析。只有这里决定主机、方法及写入属性。
const PC = 'https://drive-pc.quark.cn';
const SHARE = 'https://drive-h.quark.cn';

function endpoint(
  origin,
  method,
  path,
  { write = false, anonymous = false, verified = true } = {}
) {
  return Object.freeze({
    origin,
    method,
    path: '/1/clouddrive/' + path,
    write,
    anonymous,
    verified,
  });
}

const ENDPOINTS = Object.freeze({
  'files.list': endpoint(PC, 'GET', 'file/sort'),
  'files.info': endpoint(PC, 'GET', 'file/info'),
  'files.batchInfo': endpoint(PC, 'POST', 'file/v2/info/list'), // POST 读取，不是写入。
  'files.category': endpoint(PC, 'GET', 'file/category'),
  'files.search': endpoint(PC, 'GET', 'file/search', { verified: true }),
  'files.createFolder': endpoint(PC, 'POST', 'file', { write: true, verified: true }),
  'files.rename': endpoint(PC, 'POST', 'file/rename', { write: true, verified: true }),
  'files.move': endpoint(PC, 'POST', 'file/move', { write: true, verified: true }),
  'account.space': endpoint(PC, 'GET', 'member'),
  'tasks.get': endpoint(PC, 'GET', 'task'),
  'shares.token': endpoint(SHARE, 'POST', 'share/sharepage/token', { anonymous: true }),
  'shares.list': endpoint(SHARE, 'GET', 'share/sharepage/detail', { anonymous: true }),
  'shares.info': endpoint(PC, 'GET', 'share/sharepage/file/info', { anonymous: true }),
  'shares.save': endpoint(SHARE, 'POST', 'share/sharepage/save', { write: true }),
  'playback.play': endpoint(PC, 'POST', 'file/v2/play'), // 获取地址，不下载视频。
  'playback.history': endpoint(PC, 'GET', 'behavior/recent/list'),
  'playback.setPosition': endpoint(PC, 'POST', 'behavior/event/report', { write: true }),
});

module.exports = { ENDPOINTS, PC, SHARE };
