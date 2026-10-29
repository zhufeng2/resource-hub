'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {manage, saveEntries} = require('./manage.cjs');
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rh-manage-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  return path.join(dir, 'op.json');
}

test('rename a series folder: preview, execute, verify and reuse request without renaming twice', async t => {
  const journal = fixture(t); let writes = 0;
  const file = {fid: 'series', file_name: 'Old series', file_type: 0, pdir_fid: 'parent'};
  const client = {files: {getManyInfos: async () => [{...file}], rename: async ({name}) => {writes++; file.file_name = name; return {code: 0};}},
    folders: {readChildren: async () => [{...file}]}};
  const args = {fid: 'series', name: 'New series'};
  assert.equal((await manage(client, 'rename', args, journal)).phase, 'preview');
  assert.equal(writes, 0);
  assert.equal((await manage(client, 'rename', args, journal, true)).phase, 'verified');
  assert.equal((await manage(client, 'rename', args, journal, true)).phase, 'verified');
  assert.equal(writes, 1);
  await assert.rejects(manage(client, 'rename', {...args, name: 'Another'}, journal, true), /conflict/);
});

test('ambiguous rename acknowledgement is resolved by reading actual result, never resubmitted', async t => {
  const journal = fixture(t); let writes = 0;
  const file = {fid: 'f', file_name: 'Old', file_type: 0, pdir_fid: 'p'};
  const client = {files: {getManyInfos: async () => [{...file}], rename: async () => {
    writes++; file.file_name = 'New'; throw new Error('response lost');
  }}, folders: {readChildren: async () => [{...file}]}};
  await assert.rejects(manage(client, 'rename', {fid: 'f', name: 'New'}, journal, true));
  assert.equal((await manage(client, 'rename', {fid: 'f', name: 'New'}, journal, true)).phase, 'verified');
  assert.equal(writes, 1);
});

test('move resumes original task after pending status, verifies parent and keeps file names', async t => {
  const journal = fixture(t); let submits = 0, polls = 0;
  const files = [{fid: 'folder', file_name: 'Series', file_type: 0, pdir_fid: 'old'}];
  const client = {files: {getManyInfos: async () => files.map(f => ({...f})),
    getInfo: async fid => ({fid, file_type: 0, pdir_fid: '0'}),
    move: async ({wait}) => {assert.equal(wait, false); submits++; return {data: {task_id: 'original'}};}},
    folders: {readChildren: async parent => files.filter(f => f.pdir_fid === parent)}, tasks: {wait: async task => {
      assert.equal(task, 'original'); if (++polls === 1) throw new Error('pending');
      files[0].pdir_fid = 'new'; return {data: {status: 2}};
    }}};
  const args = {fids: ['folder'], toParentFid: 'new'};
  await assert.rejects(manage(client, 'move', args, journal, true), /pending/);
  assert.equal((await manage(client, 'move', args, journal, true)).phase, 'verified');
  assert.equal(submits, 1);
});

test('move refuses putting a series folder inside its own child', async t => {
  const journal = fixture(t); let submits = 0;
  const client = {files: {getManyInfos: async () => [{fid: 'series', file_name: 'Series', file_type: 0, pdir_fid: '0'}],
    getInfo: async fid => ({fid, file_type: 0, pdir_fid: 'series'}), move: async () => {submits++;}}};
  await assert.rejects(manage(client, 'move', {fids: ['series'], toParentFid: 'child'}, journal, true), /destination/);
  assert.equal(submits, 0);
});

test('bulk transfer uses one native request for a directory and files, maps unordered target IDs', async t => {
  const journal = fixture(t); let submits = 0, tokens = 0;
  const source = [
    {fid: 'directory', file_name: 'Whole series', file_type: 0, share_fid_token: 'private-dir'},
    {fid: 'guide', file_name: 'Guide.txt', file_type: 1, size: 8, share_fid_token: 'private-file'}];
  const saved = [{fid: 'saved-guide', file_name: 'Guide.txt', file_type: 1, size: 8, pdir_fid: 'target'},
    {fid: 'saved-directory', file_name: 'Whole series', file_type: 0, pdir_fid: 'target'}];
  const client = {shares: {parseUrl: () => 'share', getToken: async () => {tokens++; return {stoken: 'private-token'};},
    list: async ({parentFid}) => {assert.equal(parentFid, 'shared-parent'); return {data: {list: source}};},
    submitSave: async a => {submits++; assert.equal(a.files.length, 2); assert.equal(a.files[0].fid, 'directory');
      return {data: {task_id: 'batch-task'}};}},
    folders: {readChildren: async () => submits ? saved : []}, files: {getManyInfos: async () => saved},
    tasks: {wait: async () => ({data: {status: 2, save_as: {save_as_top_fids: saved.map(f => f.fid)}}})}};
  const args = {shareUrl: 'url', fids: ['guide', 'directory'], sourceParentFid: 'shared-parent', toParentFid: 'target'};
  assert.equal((await saveEntries(client, args, journal)).includes_directories, true);
  assert.equal(submits, 0);
  const result = await saveEntries(client, args, journal, true);
  assert.equal(result.phase, 'verified'); assert.equal(result.files.length, 2);
  assert.equal(result.descendants_verified, false);
  assert.equal(JSON.stringify(result).includes('private'), false);
  assert.equal(fs.readFileSync(journal, 'utf8').includes('private'), false);
  assert.equal((await saveEntries(client, {...args, fids: ['directory', 'guide']}, journal, true)).phase, 'verified');
  assert.equal(submits, 1); assert.equal(tokens, 2);
});

test('lost save acknowledgement and name conflicts never trigger duplicate submits', async t => {
  const journal = fixture(t); let submits = 0;
  const client = {shares: {parseUrl: () => 'share', getToken: async () => ({stoken: 'secret'}),
    list: async () => ({data: {list: [{fid: 'f', file_name: 'Episode', file_type: 1, size: 1, share_fid_token: 'secret'}]}}),
    submitSave: async () => {submits++; throw new Error('lost');}}, folders: {readChildren: async () => []}};
  const args = {shareUrl: 'url', fids: ['f'], sourceParentFid: '0', toParentFid: 'target'};
  await assert.rejects(saveEntries(client, args, journal, true));
  assert.equal((await saveEntries(client, args, journal, true)).error, 'outcome_unknown');
  assert.equal(submits, 1);
  await assert.rejects(saveEntries(client, {...args, fids: ['f', 'f']}, journal, true), /duplicate/);
  const other = journal + '.other';
  client.folders.readChildren = async () => [{fid: 'existing', file_name: 'Episode'}];
  assert.equal((await saveEntries(client, args, other, true)).error, 'name_conflict');
  assert.equal(submits, 1);
});
