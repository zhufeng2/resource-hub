'use strict';

const { id, pageOptions, filename } = require('./validation.cjs');

class FilesApi {
  constructor(transport, tasks) {
    this.transport = transport;
    this.tasks = tasks;
  }

  list({ parentFid = '0', page = 1, size = 100, sort = [] } = {}) {
    pageOptions(page, size);
    return this.transport.call('files.list', {
      params: {
        pdir_fid: id(parentFid),
        _page: page,
        _size: size,
        _fetch_total: 1,
        _fetch_sub_dirs: 0,
        _sort: sort.join(','),
        fetch_all_file: 1,
        fetch_risk_file_name: 1,
      },
    });
  }

  async getInfo(fid, { fullPath = false } = {}) {
    const result = await this.transport.call('files.info', {
      params: { fid: id(fid), _fetch_full_path: fullPath ? 1 : 0, need_profile_tags: 1 },
    });
    if (String(result.data?.fid) !== String(fid)) throw new Error('文件详情 fid 不匹配');
    return result.data;
  }

  async getManyInfos(fids) {
    if (!Array.isArray(fids) || !fids.length || fids.length > 100)
      throw new Error('批量详情限定 1..100 个文件ID');
    const result = await this.transport.call('files.batchInfo', {
      body: { fids: fids.map((fid) => id(fid)), fetch_pdir_name: 1, filter_secret_check_fail: 1 },
    });
    if (!Array.isArray(result.data)) throw new Error('批量详情响应结构异常');
    return result.data;
  }

  listCategory({ category = 'video', page = 1, size = 5 } = {}) {
    pageOptions(page, size);
    if (!['video', 'document', 'audio', 'image', 'bt', 'package', ''].includes(category))
      throw new Error('分类参数无效');
    return this.transport.call('files.category', {
      params: { cat: category, _page: page, _size: size, _fetch_total: 1, _sort: '' },
    });
  }

  search(query, { page = 1, size = 100 } = {}) {
    pageOptions(page, size);
    if (typeof query !== 'string' || !query.trim()) throw new Error('搜索词不能为空');
    return this.transport.call('files.search', {
      params: { q: query, _page: page, _size: size, _fetch_total: 1, _sort: '', _is_hl: 0 },
    });
  }

  async createFolder({ parentFid = '0', name }) {
    const result = await this.transport.call('files.createFolder', {
      body: {
        pdir_fid: id(parentFid),
        file_name: filename(name),
        dir_path: '',
        dir_init_lock: false,
      },
    });
    if (!result.data?.fid) throw new Error('创建响应缺少 fid；先回读父目录核对，不直接重试');
    return result;
  }

  rename({ fid, name }) {
    return this.transport.call('files.rename', {
      body: { fid: id(fid), file_name: filename(name) },
    });
  }

  async move({ fids, toParentFid, wait = true }) {
    if (!Array.isArray(fids) || !fids.length) throw new Error('请选择明确的文件或目录 ID');
    const result = await this.transport.call('files.move', {
      body: {
        action_type: 1,
        to_pdir_fid: id(toParentFid),
        filelist: fids.map((fid) => id(fid)),
        exclude_fids: [],
      },
    });
    if (result.data?.finish === true || !wait) return result;
    if (!result.data?.task_id) throw new Error('移动响应没有完成标志或任务ID；需回读核对');
    return this.tasks.wait(result.data.task_id, { intervalMs: result.metadata?.tq_gap });
  }
}

module.exports = { FilesApi };
