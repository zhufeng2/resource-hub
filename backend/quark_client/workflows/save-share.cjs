'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { fileSummary } = require('../output.cjs');
const { id } = require('../validation.cjs');
const {writeJournal: writeRecord} = require('../journal.cjs');


/** 单文件转存流程。记录不含 Cookie、stoken、文件令牌；重复运行继续原任务。 */
async function saveOneFile(
  client,
  { shareUrl, fid, toParentFid, passcode = '', journalFile, execute = false }
) {
  const pwdId = client.shares.parseUrl(shareUrl);
  id(fid);
  id(toParentFid, 'toParentFid');

  let record;
  if (journalFile && fs.existsSync(journalFile)) {
    record = JSON.parse(fs.readFileSync(journalFile, 'utf8'));
    if (
      record.pwdId !== pwdId ||
      record.source?.fid !== fid ||
      record.destination !== toParentFid
    ) {
      throw new Error('已有记录属于其他转存计划，请核对记录路径');
    }
    if (!record.taskId && !record.savedFids)
      throw new Error('已有提交意图但没有任务ID，先核对实际结果，不重新提交');
  } else {
    const token = await client.shares.getToken({ pwdId, passcode });
    const source = await client.shares.getInfo({ pwdId, stoken: token.stoken, fid });
    if (source.file_type !== 1 || !source.share_fid_token)
      throw new Error('该流程只处理一个有有效文件令牌的文件');
    const preview = { source: fileSummary(source), destination: toParentFid, count: 1 };
    if (!execute) return { phase: 'preview', ...preview };
    if (!client.transport.allowWrites) throw new Error('写入未启用');
    if (!journalFile) throw new Error('提交转存必须指定 --record 本地记录文件');
    if (path.extname(journalFile).toLowerCase() !== '.json')
      throw new Error('转存记录应使用 .json 文件');

    const before = await client.folders.readChildren(toParentFid);
    record = {
      phase: 'submitting',
      pwdId,
      ...preview,
      beforeFids: before.map((item) => String(item.fid)),
      startedAt: new Date().toISOString(),
    };
    // wx 保证多个进程不能使用同一记录文件同时提交。
    writeRecord(journalFile, record, true);
    const submitted = await client.shares.submitSave({
      pwdId,
      stoken: token.stoken,
      sourceParentFid: source.pdir_fid,
      toParentFid,
      files: [{ fid, token: source.share_fid_token }],
    });
    if (!submitted.data?.task_id) throw new Error('提交没有返回任务ID，请回读结果，不重复提交');
    record.taskId = submitted.data.task_id;
    record.intervalMs = submitted.metadata?.tq_gap;
    record.phase = 'submitted';
    writeRecord(journalFile, record);
  }

  // 未带 --execute 的预览允许查询已存在任务，但绝不重新提交。
  if (!record.savedFids) {
    const task = await client.tasks.wait(record.taskId, {
      intervalMs: record.intervalMs,
      maxAttempts: 3,
      onUpdate: (result) => {
        record.taskStatus = result.data?.status;
        writeRecord(journalFile, record);
      },
    });
    const fids = task.data?.save_as?.save_as_top_fids;
    if (!Array.isArray(fids) || fids.length !== 1)
      throw new Error('任务未返回预期的单个目标fid，需核对结果');
    record.savedFids = fids.map(String);
    record.phase = 'task-finished';
    writeRecord(journalFile, record);
  }

  const target = await client.files.getInfo(record.savedFids[0]);
  if (
    target.file_name !== record.source.file_name ||
    Number(target.size) !== Number(record.source.size) ||
    String(target.pdir_fid) !== record.destination ||
    record.beforeFids.includes(String(target.fid))
  ) {
    throw new Error('目标详情与转存计划不一致，尚未通过核验');
  }
  const after = await client.folders.readChildren(record.destination);
  if (!after.some((item) => String(item.fid) === String(target.fid)))
    throw new Error('目标目录中尚未确认新文件');
  record.phase = 'verified';
  record.savedFile = fileSummary(target);
  record.verifiedAt = new Date().toISOString();
  writeRecord(journalFile, record);
  return {
    phase: record.phase,
    taskId: record.taskId,
    file: record.savedFile,
    destination: record.destination,
  };
}

module.exports = { saveOneFile };
