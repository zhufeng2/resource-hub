'use strict';

const fs = require('node:fs');

/** 只在本地读取一行 Cookie。不记录或打印它。 */
function readCookie(file) {
  const raw = fs
    .readFileSync(file, 'utf8')
    .replace(/^\uFEFF/, '')
    .trim()
    .replace(/^Cookie:\s*/i, '');
  if (!raw || /[\r\n]/.test(raw)) throw new Error('Cookie 文件应填写一整行请求 Cookie');

  const cookies = new Map();
  for (const part of raw.split(';')) {
    const at = part.indexOf('=');
    if (at <= 0) continue;
    const name = part.slice(0, at).trim();
    const value = part.slice(at + 1).trim();
    if (!/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(name) || /[^\x20-\x7e]/.test(value)) {
      throw new Error('Cookie 格式无效');
    }
    cookies.set(name, value);
  }
  if (!cookies.size) throw new Error('Cookie 文件没有有效条目');
  return cookies;
}

// 更新仅留在本次会话及当前 API 主机，不回写 Cookie 文件。
function updateCookies(jar, headers) {
  for (const header of headers || []) {
    const pair = header.split(';', 1)[0];
    const at = pair.indexOf('=');
    if (at <= 0) continue;
    const name = pair.slice(0, at).trim();
    const value = pair.slice(at + 1);
    if (!value || /;\s*max-age=0(?:;|$)/i.test(header)) jar.delete(name);
    else jar.set(name, value);
  }
}

module.exports = { readCookie, updateCookies };
