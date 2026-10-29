'use strict';

function id(value, label = 'fid') {
  if (typeof value !== 'string' || !value.trim()) throw new Error(label + ' 必须为非空字符串');
  return value;
}

function pageOptions(page, size, maximum = 100) {
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    !Number.isSafeInteger(size) ||
    size < 1 ||
    size > maximum
  ) {
    throw new Error('分页参数无效，size 上限为 ' + maximum);
  }
}

function filename(value) {
  if (
    typeof value !== 'string' ||
    !value.trim() ||
    ['.', '..'].includes(value) ||
    /[\x00-\x1f\\/:<>|*?,%]/.test(value)
  ) {
    throw new Error('名称为空或含前端禁止的字符');
  }
  return value;
}

function parseShareUrl(value) {
  const url = new URL(value);
  const match = url.pathname.match(/^\/s\/([a-zA-Z0-9]+)\/?$/);
  if (url.origin !== 'https://pan.quark.cn' || url.username || url.password || !match) {
    throw new Error('请输入 https://pan.quark.cn/s/分享ID 格式的链接');
  }
  return match[1];
}

module.exports = { id, pageOptions, filename, parseShareUrl };
