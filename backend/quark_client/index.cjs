'use strict';

const { Transport, ApiError } = require('./transport.cjs');
const { FilesApi } = require('./files.cjs');
const { FoldersApi } = require('./folders.cjs');
const { SharesApi } = require('./shares.cjs');
const { PlaybackApi } = require('./playback.cjs');
const { TasksApi } = require('./tasks.cjs');
const { AccountApi } = require('./account.cjs');

/** 统一入口。构造/导入均不发请求，所有写操作默认禁用。 */
class QuarkClient {
  constructor(options = {}) {
    this.transport = new Transport(options);
    this.tasks = new TasksApi(this.transport, options);
    this.files = new FilesApi(this.transport, this.tasks);
    this.folders = new FoldersApi(this.files);
    this.shares = new SharesApi(this.transport);
    this.playback = new PlaybackApi(this.transport, this.files);
    this.account = new AccountApi(this.transport);
  }
}

module.exports = { QuarkClient, ApiError };
