'use strict';

const { id, pageOptions } = require('./validation.cjs');
const { progressSummary } = require('./output.cjs');

class PlaybackApi {
  constructor(transport, files) {
    this.transport = transport;
    this.files = files;
  }

  async getProgress(fid) {
    return progressSummary(await this.files.getInfo(fid));
  }

  getHistory({ size = 5, maxTime } = {}) {
    pageOptions(1, size, 50);
    return this.transport.call('playback.history', {
      params: {
        q_cat: 'video',
        q_source: 'PLAY',
        q_plat: '',
        item_size: size,
        max_tm: maxTime,
      },
    });
  }

  /** 获取服务端播放地址。返回值含签名 URL，调用者不要记录完整响应。 */
  async getPlayInfo(
    fid,
    {
      resolutions = ['normal', 'low', 'high', 'super', '2k', '4k'],
      supports = ['fmp4', 'm3u8'],
    } = {}
  ) {
    const result = await this.transport.call('playback.play', {
      body: {
        fid: id(fid),
        resolutions: resolutions.join(','),
        supports: supports.join(','),
      },
    });
    return result.data;
  }

  /** 只上报一次；是否真正保存，必须随后通过 getProgress 独立确认。 */
  setPosition({ fid, seconds }) {
    if (!Number.isSafeInteger(seconds) || seconds < 0) throw new Error('播放位置必须为非负整数秒');
    return this.transport.call('playback.setPosition', {
      body: {
        source: 'PLAY',
        targets: [id(fid)],
        extra: { play_progress: seconds },
      },
    });
  }
}

module.exports = { PlaybackApi };
