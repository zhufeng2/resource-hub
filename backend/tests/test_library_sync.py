"""Account isolation, replay-safe writes, tombstones and progress round trips."""
import unittest

from . import test_service as fixtures
from . import test_web as web_fixtures


def operation(kind='favorite', media_id='tmdb:movie:1', revision=0, mutation='a' * 32, deleted=False):
    data = {'updatedAt': 1000, 'media': {'id': media_id, 'title': 'Film', 'type': 'MOVIE'}}
    if kind == 'watch':
        data.update(fid='1' * 32, title='01.mkv', positionMs=120000, durationMs=1800000, completed=False)
    return dict(kind=kind, id=media_id, base_revision=revision, mutation_id=mutation, deleted=deleted, data={} if deleted else data)


class LibrarySyncTests(unittest.TestCase):
    setUp = fixtures.ServiceTests.setUp
    cleanup_temp = fixtures.ServiceTests.cleanup_temp
    web_login = web_fixtures.WebTests.web_login

    def send(self, changes, headers):
        return self.client.post('/api/library', json={'changes': changes}, headers=headers)

    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(self.client.get('/api/library').status_code, 401)
        self.web_login()
        self.assertEqual(self.send([operation()], {}).status_code, 403)
        self.assertEqual(self.client.get('/api/library?after=-1').status_code, 400)

    def test_favorites_are_visible_to_same_account_but_not_another_account(self):
        headers = self.web_login()
        saved = self.send([operation()], headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.web_login('bob')
        self.assertEqual(self.client.get('/api/library').json()['items'], [])
        self.web_login('alice')
        self.assertEqual(self.client.get('/api/library').json()['items'][0]['data']['media']['title'], 'Film')

    def test_lost_response_replay_does_not_advance_revision(self):
        headers = self.web_login()
        first = self.send([operation()], headers).json()
        second = self.send([operation()], headers).json()
        self.assertEqual(first, second)

    def test_stale_device_cannot_resurrect_deleted_item(self):
        headers = self.web_login()
        version = self.send([operation()], headers).json()['items'][0]['revision']
        delete = operation(revision=version, mutation='b' * 32, deleted=True)
        self.assertTrue(self.send([delete], headers).json()['items'][0]['deleted'])
        stale = operation(revision=version, mutation='c' * 32)
        reply = self.send([stale], headers).json()
        self.assertEqual(reply['conflicts'], 1)
        self.assertTrue(reply['items'][0]['deleted'])
        self.assertTrue(self.client.get('/api/library').json()['items'][0]['deleted'])

    def test_progress_and_directory_reference_round_trip(self):
        headers = self.web_login()
        change = operation(kind='watch')
        change['data'].update(destination='2' * 32, topFids=['3' * 32], sourceUrl='https://pan.quark.cn/s/fixture')
        result = self.send([change], headers)
        self.assertEqual(result.status_code, 200, result.text)
        data = self.client.get('/api/library').json()['items'][0]['data']
        self.assertEqual(data['positionMs'], 120000)
        self.assertEqual(data['durationMs'], 1800000)
        self.assertEqual(data['topFids'], ['3' * 32])

    def test_unknown_credentials_and_invalid_payloads_are_rejected_atomically(self):
        headers = self.web_login()
        invalid = operation(media_id='tmdb:movie:2', mutation='b' * 32)
        invalid['data']['cookie'] = 'not-allowed'
        result = self.send([operation(), invalid], headers)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get('/api/library').json()['items'], [])
        invalid = operation(kind='watch')
        invalid['data']['sourceUrl'] = 'https://evil.example/stream?token=secret'
        self.assertEqual(self.send([invalid], headers).status_code, 400)

    def test_cursor_pagination_does_not_skip_other_device_changes(self):
        self.web_login()
        alice = self.client.get('/api/session').json()
        changes = [operation(media_id=f'tmdb:movie:{i}', mutation=f'{i:032x}') for i in range(1, 103)]
        self.store.library_merge(alice['id'], changes)
        first = self.client.get('/api/library').json()
        self.assertEqual(len(first['items']), 100)
        self.assertTrue(first['has_more'])
        second = self.client.get('/api/library?after=' + str(first['cursor'])).json()
        self.assertEqual(len(second['items']), 2)
        self.assertFalse(second['has_more'])

    def test_parallel_base_revisions_do_not_overwrite_confirmed_progress(self):
        headers = self.web_login()
        first = self.send([operation(kind='watch')], headers).json()['items'][0]
        progress = operation(kind='watch', revision=first['revision'], mutation='b' * 32)
        progress['data']['positionMs'] = 300000
        self.send([progress], headers)
        older = operation(kind='watch', revision=first['revision'], mutation='c' * 32)
        reply = self.send([older], headers).json()
        self.assertEqual(reply['conflicts'], 1)
        self.assertEqual(reply['items'][0]['data']['positionMs'], 300000)

    def test_newer_playback_event_can_merge_a_stale_base_without_resurrecting_deletion(self):
        headers = self.web_login()
        first = self.send([operation(kind='watch')], headers).json()['items'][0]
        newer = operation(kind='watch', revision=0, mutation='d' * 32)
        newer['data'].update(updatedAt=2000, positionMs=600000)
        merged = self.send([newer], headers).json()
        self.assertEqual(merged['conflicts'], 0)
        self.assertEqual(merged['items'][0]['data']['positionMs'], 600000)
        deleted = operation(kind='watch', revision=merged['items'][0]['revision'], mutation='e' * 32, deleted=True)
        self.send([deleted], headers)
        newer['mutation_id'] = 'f' * 32
        newer['data']['updatedAt'] = 3000
        self.assertTrue(self.send([newer], headers).json()['items'][0]['deleted'])

    def test_large_episode_library_can_sync_a_directory_without_a_large_fid_list(self):
        headers = self.web_login()
        change = operation(kind='watch')
        change['data'].update(destination='2' * 32, sourceUrl='https://pan.quark.cn/s/fixture')
        self.assertEqual(self.send([change], headers).status_code, 200)

    def test_deleting_account_removes_its_library_and_revision_cursor(self):
        headers = self.web_login('bob')
        user_id = int(self.client.get('/api/session').json()['id'])
        self.send([operation()], headers)
        self.store.add_user('admin', fixtures.PASSWORD, 5, is_admin=True)
        headers = self.web_login('admin')
        response = self.client.request('DELETE', f'/api/users/{user_id}', json={'username': 'bob'}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        with self.store.connection() as db:
            for table in ('media_library', 'media_library_versions'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?', (user_id,)).fetchone()[0], 0)
