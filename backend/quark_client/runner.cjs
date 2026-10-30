'use strict';
// One isolated process per call; never use a global account or accept a cookieFile.
const fs = require('node:fs');
const { QuarkClient } = require('./index.cjs');
const { fileSummary } = require('./output.cjs');
const { filename, id } = require('./validation.cjs');
const { saveOneFile } = require('./workflows/save-share.cjs');
const { manage, saveEntries } = require('./workflows/manage.cjs');
const { resetFolderProgress, resetSummary } = require('./workflows/reset-progress.cjs');
const {writeJournal} = require('./journal.cjs');
const {createText} = require('./workflows/create-text.cjs');

function page(result, args) {
  const list = result.data?.list;
  if (!Array.isArray(list)) throw new Error('invalid_list');
  const total = Number(result.metadata?._total ?? result.metadata?.total);
  return { files: list.map(fileSummary), page: args.page || 1, size: args.size || 50,
    total: Number.isFinite(total) ? total : null,
    has_more: Number.isFinite(total) ? (args.page || 1) * (args.size || 50) < total : list.length === (args.size || 50) };
}

async function dispatch(input, createClient = options => new QuarkClient(options)) {
  const cookies = new Map(input.cookie.split(';').filter(x => x.trim()).map(part => {
    const at = part.indexOf('=');
    return [part.slice(0, at).trim(), part.slice(at + 1).trim()];
  }));
  const client = createClient({ cookies, allowWrites: input.execute === true, timeoutMs: input.action==='reset_progress'?5000:10000 });
  const a = input.args;
  switch (input.action) {
    case 'space': {
      const result = await client.account.getSpace();
      const data = result.data || {};
      return { total: data.total_capacity ?? null, used: data.use_capacity ?? null };
    }
    case 'list': return page(await client.files.list(a), a);
    case 'search': return { ...page(await client.files.search(a.query, a), a), verification: 'live_verified' };
    case 'info': return { file: fileSummary(await client.files.getInfo(a.fid)) };
    case 'share': {
      const pwdId = client.shares.parseUrl(a.shareUrl);
      const token = await client.shares.getToken({ pwdId, passcode: a.passcode || '' });
      return page(await client.shares.list({ ...a, pwdId, stoken: token.stoken }), a);
    }
    case 'operation': {
      // Status must remain queryable after an interrupted worker leaves a lock.
      const r = JSON.parse(fs.readFileSync(input.journal, 'utf8'));
      if(r.kind==='reset_progress')return {...resetSummary(r),locked:fs.existsSync(input.journal+'.lock')};
      let status = r.taskStatus ?? null;
      if (r.taskId && r.phase !== 'verified') status = (await client.tasks.get(r.taskId)).data?.status ?? null;
      return { phase: r.phase, task_status: status, file: r.savedFile || null, files: r.savedFiles || null,
        content_verified: r.kind==='text' ? r.phase==='verified' : undefined,
        verification_scope: r.verificationScope, descendants_verified: r.descendantsVerified,
        destination: r.destination, verified: r.phase === 'verified',
        locked: fs.existsSync(input.journal + '.lock'),
        message: status === 2 && r.phase !== 'verified' ? '任务结束，需用原参数和请求编号续查并核验；若有遗留锁先由管理员核对。' : undefined };
    }
    case 'save':
    case 'create_text':
    case 'reset_progress':
    case 'save_entries':
    case 'rename':
    case 'move':
    case 'create_folder': {
      if (!input.journal) throw new Error('missing_journal');
      // Cross-worker exclusion. A crash leaves the lock for deliberate inspection.
      const lock = input.journal + '.lock';
      let fd;
      try { fd = fs.openSync(lock, 'wx', 0o600); }
      catch { return { error: 'operation_busy', message: '原操作正在进行或中断后待核对，请勿更换编号重提。' }; }
      try {
        if(input.action==='create_text')return await createText(client,a,input.journal,input.execute===true);
        if(input.action==='reset_progress')return await resetFolderProgress(client,a,input.journal,input.execute===true);
        if (input.action === 'save_entries') return await saveEntries(client, a, input.journal, input.execute === true);
        if (['rename', 'move'].includes(input.action)) return await manage(client, input.action, a, input.journal, input.execute === true);
        if (input.action === 'create_folder') {
          id(a.parentFid); filename(a.name);
          if (fs.existsSync(input.journal)) {
            const r = JSON.parse(fs.readFileSync(input.journal, 'utf8'));
            if (r.kind !== 'folder' || r.name !== a.name || r.destination !== a.parentFid) throw new Error('plan_conflict');
            if (r.savedFile) return { phase: r.phase, file: r.savedFile };
            return { error: 'outcome_unknown', message: '已存在建目录意图，请读取父目录核对，不重复提交。' };
          }
          if (!input.execute) return { phase: 'preview', parent: a.parentFid, name: a.name };
          // Do not reuse an existing same-name file or create another same-name folder.
          const before = await client.folders.readChildren(a.parentFid);
          if (before.some(f => f.file_name === a.name)) return { error: 'name_exists', message: '父目录已有同名条目，请读取目录确认。' };
          const r = { kind: 'folder', phase: 'submitting', name: a.name, destination: a.parentFid };
          writeJournal(input.journal, r, true);
          const created = await client.files.createFolder(a);
          const file = await client.files.getInfo(created.data.fid);
          if (file.file_name !== a.name || String(file.pdir_fid) !== a.parentFid || file.file_type !== 0) throw new Error('verification_failed');
          r.savedFile = fileSummary(file); r.phase = 'verified';
          writeJournal(input.journal, r);
          return { phase: r.phase, file: r.savedFile };
        }
        return await saveOneFile(client, { ...a, journalFile: input.journal, execute: input.execute === true });
      } finally { fs.closeSync(fd); fs.unlinkSync(lock); }
    }
    default: throw new Error('unsupported_action');
  }
}

async function main() {
  const chunks = []; let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 256 * 1024) throw new Error('input_limit');
    chunks.push(chunk);
  }
  return dispatch(JSON.parse(Buffer.concat(chunks).toString('utf8')));
}
if (require.main === module) main().then(result => process.stdout.write(JSON.stringify(result))).catch(error => {
  // Exception text may contain tokens, file paths or response bodies. Never return it.
  process.stdout.write(JSON.stringify({ error: 'quark_operation_failed',
    message: '操作未确认成功，请检查账号状态、参数和原操作记录；不要更换请求编号重复提交。',
    reason: /^(invalid_upload_(pre|bucket|auth|callback|etag)|unsupported_upload_host|upload_[a-z_]+|invalid_text_file|text_size_limit)$/.test(error.message) ? error.message : undefined,
    http_status: Number.isInteger(error.httpStatus) ? error.httpStatus : undefined,
    business_code: Number.isInteger(error.businessCode) ? error.businessCode : undefined,
    outcome_unknown: error.outcomeUnknown === true }));
});
module.exports = { dispatch, page };
