'use strict';
const fs = require('node:fs');
const { id, filename } = require('../validation.cjs');
const { fileSummary } = require('../output.cjs');
const {writeJournal: write} = require('../journal.cjs');

function selectedIds(fids) {
  if (!Array.isArray(fids) || !fids.length || fids.length > 100) throw new Error('select_1_to_100');
  fids.forEach(fid => id(fid));
  if (new Set(fids).size !== fids.length) throw new Error('duplicate_selection');
  return [...fids].sort();
}
function existing(journal, plan) {
  if (!fs.existsSync(journal)) return null;
  const r = JSON.parse(fs.readFileSync(journal, 'utf8'));
  if (JSON.stringify(r.plan) !== JSON.stringify(plan)) throw new Error('request_id_plan_conflict');
  return r;
}
const uncertain = () => ({error: 'outcome_unknown', message: '已记录提交意图，尚未核验成功；只查询原操作，不换编号重提。'});
function summary(r) {
  return {phase: r.phase, files: r.savedFiles, destination: r.destination,
    verification_scope: r.verificationScope || 'selected_entries',
    descendants_verified: r.descendantsVerified ?? null};
}
async function poll(client, r, journal) {
  if (!r.taskId || r.taskFinished) return;
  const task = await client.tasks.wait(r.taskId, {maxAttempts: 3, intervalMs: r.intervalMs,
    onUpdate: result => {r.taskStatus = result.data?.status; write(journal, r);}});
  r.taskFinished = true; r.taskStatus = task.data?.status;
  if (r.kind === 'save_entries') {
    const fids = task.data?.save_as?.save_as_top_fids;
    if (!Array.isArray(fids) || fids.length !== r.source.length || new Set(fids).size !== fids.length) throw new Error('unexpected_saved_entries');
    r.savedFids = fids.map(String);
  }
  r.phase = 'task-finished'; write(journal, r);
}

async function manage(client, action, a, journal, execute = false) {
  const fids = selectedIds(action === 'rename' ? [a.fid] : a.fids);
  if (action === 'rename') filename(a.name);
  else id(a.toParentFid, 'destination');
  if (action === 'move' && fids.includes(a.toParentFid)) throw new Error('cannot_move_into_self');
  const plan = action === 'rename' ? {action, fids, name: a.name} : {action, fids, toParentFid: a.toParentFid};
  let r = existing(journal, plan);
  if (r?.phase === 'verified') return summary(r);
  if (!r) {
    const source = await client.files.getManyInfos(fids);
    if (source.length !== fids.length || fids.some(fid => !source.some(f => String(f.fid) === fid))) throw new Error('source_mismatch');
    const destination = action === 'rename' ? String(source[0].pdir_fid) : a.toParentFid;
    if (action === 'move') {
      // Walk the actual destination ancestry; do not move a folder into its descendants.
      let parent = destination;
      const seen = new Set();
      for (let depth = 0; parent !== '0'; depth++) {
        if (depth >= 64 || seen.has(parent) || fids.includes(parent)) throw new Error('invalid_move_destination');
        seen.add(parent);
        const folder = await client.files.getInfo(parent);
        if (folder.file_type !== 0) throw new Error('destination_not_directory');
        parent = id(String(folder.pdir_fid));
      }
    }
    const before = await client.folders.readChildren(destination);
    const names = source.map(f => action === 'rename' ? a.name : f.file_name);
    if (new Set(names).size !== names.length || before.some(f => names.includes(f.file_name) && !fids.includes(String(f.fid)))) {
      return {error: 'name_conflict', message: '目标存在同名条目，未覆盖或合并，请先确定处理范围。'};
    }
    if (!execute) return {phase: 'preview', plan, files: source.map(fileSummary), destination};
    r = {kind: action, plan, phase: 'submitting', destination, source: source.map(fileSummary)};
    write(journal, r, true);
    const response = action === 'rename' ? await client.files.rename({fid: fids[0], name: a.name})
      : await client.files.move({fids, toParentFid: destination, wait: false});
    r.acknowledged = true; r.phase = 'submitted';
    if (response.data?.task_id) {r.taskId = response.data.task_id; r.intervalMs = response.metadata?.tq_gap;}
    write(journal, r);
  }
  await poll(client, r, journal);
  const current = await client.files.getManyInfos(fids);
  const valid = current.length === fids.length && r.source.every(source => current.some(f =>
    String(f.fid) === String(source.fid) && String(f.pdir_fid) === r.destination &&
    f.file_name === (action === 'rename' ? a.name : source.file_name)));
  if (!valid) return {...uncertain(), phase: r.phase};
  const after = await client.folders.readChildren(r.destination);
  if (fids.some(fid => !after.some(f => String(f.fid) === fid))) return {...uncertain(), phase: r.phase};
  r.savedFiles = current.map(fileSummary); r.phase = 'verified'; write(journal, r);
  return summary(r);
}

async function saveEntries(client, a, journal, execute = false) {
  const fids = selectedIds(a.fids), pwdId = client.shares.parseUrl(a.shareUrl);
  id(a.sourceParentFid); id(a.toParentFid);
  const plan = {action: 'save_entries', pwdId, fids, sourceParentFid: a.sourceParentFid, toParentFid: a.toParentFid};
  let r = existing(journal, plan);
  if (r?.phase === 'verified') return summary(r);
  if (!r) {
    const token = await client.shares.getToken({pwdId, passcode: a.passcode || ''});
    const found = new Map(); let ended = false;
    for (let page = 1; page <= 20; page++) {
      const response = await client.shares.list({pwdId, stoken: token.stoken, parentFid: a.sourceParentFid, page, size: 100});
      const list = response.data?.list;
      if (!Array.isArray(list)) throw new Error('invalid_share_list');
      for (const file of list) if (fids.includes(String(file.fid))) found.set(String(file.fid), file);
      if (found.size === fids.length) {ended = true; break;}
      const total = response.metadata?._total;
      if ((Number.isFinite(total) && page * 100 >= total) || (!Number.isFinite(total) && list.length < 100)) break;
    }
    if (!ended) throw new Error('selected_entries_not_found_in_parent');
    const source = fids.map(fid => found.get(fid));
    if (source.some(f => ![0, 1].includes(f.file_type) || !f.share_fid_token)) throw new Error('invalid_share_entry');
    const names = source.map(f => f.file_name);
    const before = await client.folders.readChildren(a.toParentFid);
    if (new Set(names).size !== names.length || before.some(f => names.includes(f.file_name))) {
      return {error: 'name_conflict', message: '目标已有同名条目，未重复转存或合并目录。'};
    }
    if (!execute) return {phase: 'preview', files: source.map(fileSummary), count: fids.length,
      destination: a.toParentFid, includes_directories: source.some(f => f.file_type === 0)};
    r = {kind: 'save_entries', plan, phase: 'submitting', destination: a.toParentFid,
      source: source.map(fileSummary), beforeFids: before.map(f => String(f.fid))};
    write(journal, r, true);
    const submitted = await client.shares.submitSave({pwdId, stoken: token.stoken,
      sourceParentFid: a.sourceParentFid, toParentFid: a.toParentFid,
      files: source.map(f => ({fid: String(f.fid), token: f.share_fid_token}))});
    if (!submitted.data?.task_id) throw new Error('missing_task_id');
    r.taskId = submitted.data.task_id; r.intervalMs = submitted.metadata?.tq_gap; r.phase = 'submitted'; write(journal, r);
  }
  if (!r.taskId && !r.savedFids) return uncertain();
  await poll(client, r, journal);
  if (!r.savedFids) return uncertain();
  const targets = await client.files.getManyInfos(r.savedFids);
  const after = await client.folders.readChildren(r.destination);
  const valid = targets.length === r.source.length && r.source.every(s => targets.filter(f =>
    f.file_name === s.file_name && f.file_type === s.file_type && String(f.pdir_fid) === r.destination &&
    (s.file_type === 0 || Number(f.size) === Number(s.size)) &&
    r.savedFids.includes(String(f.fid)) && !r.beforeFids.includes(String(f.fid)) &&
    after.some(item => String(item.fid) === String(f.fid))).length === 1);
  if (!valid) return {...uncertain(), phase: r.phase};
  r.savedFiles = targets.map(fileSummary); r.phase = 'verified';
  // Native directory transfer: verify selected top-level entries, do not assert a recursive audit.
  r.verificationScope = 'selected_top_level_entries';
  r.descendantsVerified = r.source.some(f => f.file_type === 0) ? false : null;
  write(journal, r); return summary(r);
}
module.exports = {manage, saveEntries};
