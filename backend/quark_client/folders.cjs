'use strict';

const { id, filename } = require('./validation.cjs');

class FoldersApi {
  constructor(files) {
    this.files = files;
  }

  /** 有界分页。达到上限时拒绝“未发现即不存在”的推断。 */
  async readChildren(parentFid, { maxPages = 20 } = {}) {
    if (!Number.isSafeInteger(maxPages) || maxPages < 1 || maxPages > 100)
      throw new Error('目录分页上限范围为 1..100');
    const items = [];
    for (let page = 1; page <= maxPages; page++) {
      const result = await this.files.list({ parentFid, page, size: 100 });
      const list = result.data?.list;
      if (!Array.isArray(list)) throw new Error('目录列表结构异常');
      items.push(...list);
      const total = result.metadata?._total;
      if (Number.isFinite(total)) {
        if (page * 100 >= total) return items;
        if (!list.length) throw new Error('目录提前返回空页，总数尚未覆盖；停止判断');
      } else if (list.length < 100) return items;
    }
    throw new Error('目录分页未读完，不能安全判断对象不存在');
  }

  /** 按真实父目录 ID 逐层复用/创建，创建后独立回读。 */
  async ensurePath(parts, { parentFid = '0', maxPagesPerLevel = 20 } = {}) {
    if (!Array.isArray(parts) || !parts.length) throw new Error('parts 应为非空目录名数组');
    parts.forEach(filename);
    let current = id(parentFid);
    const steps = [];
    for (const name of parts) {
      const list = await this.readChildren(current, { maxPages: maxPagesPerLevel });
      const found = list.filter((item) => item.file_name === name);
      if (found.length > 1 || found.some((item) => item.file_type !== 0))
        throw new Error('同名文件或目录存在歧义，停止自动创建');
      if (found.length) {
        current = id(found[0].fid);
        steps.push({ name, fid: current, created: false });
        continue;
      }
      const parent = current;
      const result = await this.files.createFolder({ parentFid: parent, name });
      current = id(result.data.fid);
      const check = await this.files.getInfo(current);
      if (check.file_name !== name || String(check.pdir_fid) !== parent || check.file_type !== 0) {
        throw new Error('创建目录后的独立详情核验失败');
      }
      steps.push({ name, fid: current, created: true });
    }
    return { fid: current, steps };
  }
}

module.exports = { FoldersApi };
