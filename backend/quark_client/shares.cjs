'use strict';

const { id, pageOptions, parseShareUrl } = require('./validation.cjs');

class SharesApi {
  constructor(transport) {
    this.transport = transport;
  }

  parseUrl(url) {
    return parseShareUrl(url);
  }

  async getToken({ pwdId, passcode = '', authenticated = false }) {
    const result = await this.transport.call('shares.token', {
      authenticated,
      body: {
        pwd_id: id(pwdId, 'pwdId'),
        passcode,
        support_visit_limit_private_share: true,
      },
    });
    if (!result.data?.stoken) throw new Error('未获得分享访问令牌');
    return result.data;
  }

  list({
    pwdId,
    stoken,
    parentFid = '0',
    page = 1,
    size = 50,
    fullPath = false,
    authenticated = false,
  }) {
    pageOptions(page, size);
    const root = parentFid === '0';
    return this.transport.call('shares.list', {
      authenticated,
      params: {
        ver: 2,
        pwd_id: id(pwdId, 'pwdId'),
        stoken: id(stoken, 'stoken'),
        pdir_fid: id(parentFid),
        force: 0,
        _page: page,
        _size: size,
        _fetch_total: 1,
        _sort: '',
        _fetch_banner: root ? 1 : 0,
        _fetch_share: root ? 1 : 0,
        fetch_relate_conversation: root ? 1 : 0,
        ...(fullPath ? { fetch_share_full_path: 1 } : {}),
      },
    });
  }

  async getInfo({ pwdId, stoken, fid, authenticated = false }) {
    const result = await this.transport.call('shares.info', {
      authenticated,
      params: {
        pwd_id: id(pwdId, 'pwdId'),
        stoken: id(stoken, 'stoken'),
        fid: id(fid),
      },
    });
    if (String(result.data?.fid) !== String(fid)) throw new Error('分享详情 fid 不匹配');
    return result.data;
  }

  /** 仅提交明确选择的条目，不自动全选、不默认选择目标目录、不自动重提。 */
  submitSave({ pwdId, stoken, sourceParentFid, toParentFid, files }) {
    if (!Array.isArray(files) || !files.length || files.length > 100)
      throw new Error('本封装一次转存限定 1..100 个明确条目');
    const selected = files.map((file) => ({
      fid: id(file.fid),
      token: id(file.token, 'share_fid_token'),
    }));
    if (new Set(selected.map((file) => file.fid)).size !== selected.length)
      throw new Error('选中文件 ID 重复');
    return this.transport.call('shares.save', {
      body: {
        pwd_id: id(pwdId, 'pwdId'),
        stoken: id(stoken, 'stoken'),
        pdir_fid: id(sourceParentFid),
        to_pdir_fid: id(toParentFid),
        fid_list: selected.map((file) => file.fid),
        fid_token_list: selected.map((file) => file.token),
        scene: 'link',
      },
    });
  }
}

module.exports = { SharesApi };
