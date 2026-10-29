'use strict';

const { id } = require('./validation.cjs');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class TasksApi {
  constructor(transport, { delay = sleep } = {}) {
    this.transport = transport;
    this.delay = delay;
  }

  get(taskId, retryIndex = 0) {
    return this.transport.call('tasks.get', {
      params: { task_id: id(taskId, 'taskId'), retry_index: retryIndex },
    });
  }

  /** 只轮询原任务；失败、暂停、超时都不会重新提交写入。 */
  async wait(taskId, { intervalMs = 1000, maxAttempts = 30, onUpdate } = {}) {
    id(taskId, 'taskId');
    if (!Number.isSafeInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 120) {
      throw new Error('轮询次数范围为 1..120');
    }
    const interval = Math.max(500, Math.min(Number(intervalMs) || 1000, 5000));
    for (let retry = 0; retry < maxAttempts; retry++) {
      await this.delay(interval);
      const result = await this.get(taskId, retry);
      await onUpdate?.(result);
      if (result.data?.status === 2) return result;
      if (result.data?.status === 3) throw new Error('任务失败：' + taskId);
      if (result.data?.status === 4) throw new Error('任务暂停：' + taskId + '；未自动恢复');
    }
    throw new Error('任务尚未终结：' + taskId + '；继续查询此任务，不重复提交');
  }
}

module.exports = { TasksApi };
