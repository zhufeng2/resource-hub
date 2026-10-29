'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { dispatch } = require('./runner.cjs');
const { saveOneFile } = require('./workflows/save-share.cjs');

test('concurrent requests have separate cookies and output strips private fields', async () => {
  const observed = [];
  const create = options => ({files: {list: async () => {
    observed.push(options.cookies.get('session'));
    await new Promise(resolve => setTimeout(resolve, 2));
    return {data: {list: [{fid: 'f', file_name: 'movie', stoken: 'secret', download_url: 'secret'}]}, metadata: {_total: 1}};
  }}});
  const results = await Promise.all(['alice', 'bob'].map(name => dispatch({
    cookie: 'session=' + name, action: 'list', args: {page: 1, size: 50}}, create)));
  assert.deepEqual(observed.sort(), ['alice', 'bob']);
  assert.equal(JSON.stringify(results).includes('secret'), false);
  assert.equal(results[0].has_more, false);
});

test('share list keeps anonymous defaults and hides share tokens', async () => {
  const client = {shares: {
    parseUrl: () => 'share', getToken: async () => ({stoken: 'private'}),
    list: async a => { assert.equal(a.authenticated, undefined); assert.equal(a.stoken, 'private');
      return {data: {list: [{fid: 'file', share_fid_token: 'private'}]}}; }
  }};
  const result = await dispatch({cookie: 'session=alice', action: 'share', args: {}}, () => client);
  assert.equal(JSON.stringify(result).includes('private'), false);
});

test('folder preview is read-only and retries never create duplicates', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rh-quark-'));
  try {
    let writes = 0;
    const file = {fid: 'new', pdir_fid: 'parent', file_type: 0, file_name: 'Movies'};
    const client = {folders: {readChildren: async () => []}, files: {
      createFolder: async () => { writes++; return {data: {fid: 'new'}}; }, getInfo: async () => file }};
    const input = {cookie: 'session=a', action: 'create_folder', args: {parentFid: 'parent', name: 'Movies'}, journal: path.join(dir, 'op.json')};
    assert.equal((await dispatch(input, () => client)).phase, 'preview');
    assert.equal(writes, 0);
    for (let i = 0; i < 2; i++) assert.equal((await dispatch({...input, execute: true}, () => client)).phase, 'verified');
    assert.equal(writes, 1);
    fs.writeFileSync(input.journal + '.lock', '');
    assert.equal((await dispatch({...input, execute: true}, () => client)).error, 'operation_busy');
    assert.equal(writes, 1);
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test('save submission resumes the same task and verifies the saved target', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rh-save-'));
  try {
    let writes = 0, poll = 0;
    const source = {fid: 'source', file_type: 1, file_name: 'movie', size: 10, pdir_fid: 'shared', share_fid_token: 'private'};
    const target = {...source, fid: 'saved', pdir_fid: 'destination'};
    const client = {transport: {allowWrites: true}, shares: {
      parseUrl: () => 'share', getToken: async () => ({stoken: 'private'}), getInfo: async () => source,
      submitSave: async () => {writes++; return {data: {task_id: 'task'}};}
    }, folders: {readChildren: async () => writes ? [target] : []},
    files: {getInfo: async () => target}, tasks: {wait: async task => {
      assert.equal(task, 'task'); if (++poll === 1) throw new Error('still pending');
      return {data: {save_as: {save_as_top_fids: ['saved']}}};
    }}};
    const args = {shareUrl: 'url', fid: 'source', toParentFid: 'destination', journalFile: path.join(dir, 'op.json'), execute: true};
    await assert.rejects(saveOneFile(client, args), /pending/);
    assert.equal((await saveOneFile(client, args)).phase, 'verified');
    assert.equal((await saveOneFile(client, args)).phase, 'verified');
    assert.equal(writes, 1);
    assert.equal(fs.readFileSync(args.journalFile, 'utf8').includes('private'), false);
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test('status can query the original task while a stale lock blocks writes', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rh-status-'));
  try {
    const journal = path.join(dir, 'op.json');
    fs.writeFileSync(journal, JSON.stringify({phase: 'submitted', taskId: 'original', destination: 'target'}));
    fs.writeFileSync(journal + '.lock', '');
    const result = await dispatch({cookie: 'session=a', action: 'operation', args: {}, journal}, () => ({
      tasks: {get: async task => { assert.equal(task, 'original'); return {data: {status: 2}}; }}
    }));
    assert.equal(result.task_status, 2);
    assert.equal(result.verified, false);
    assert.equal(result.locked, true);
    assert.equal(fs.existsSync(journal + '.lock'), true);
    assert.equal(JSON.stringify(result).includes('original'), false);
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});
