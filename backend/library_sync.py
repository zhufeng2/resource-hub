"""Account-scoped metadata sync. Strict fields exclude cookies and signed playback URLs."""
import json
import re
from urllib.parse import urlsplit

MEDIA_ID = re.compile(r'tmdb:(movie|tv):[1-9][0-9]{0,11}')
FID = re.compile(r'[a-f0-9]{32}')


def integer(value, maximum=9_007_199_254_740_991):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid_integer')


def text(value, maximum):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError('invalid_text')


def metadata(value, media_id):
    allowed = {'id', 'title', 'subtitle', 'year', 'type', 'score', 'genre', 'overview', 'artwork',
               'poster', 'backdrop', 'popularity', 'votes', 'date', 'origins', 'language'}
    if not isinstance(value, dict) or set(value) - allowed or value.get('id') != media_id:
        raise ValueError('invalid_metadata')
    for name, limit in [('title', 300), ('subtitle', 300), ('genre', 300), ('overview', 1200), ('date', 20), ('language', 20)]:
        text(value.get(name, ''), limit)
    if value.get('type') not in ('MOVIE', 'TV', 'ANIME'):
        raise ValueError('invalid_type')
    for name in ('poster', 'backdrop'):
        url = value.get(name)
        if url is not None:
            text(url, 500)
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.netloc != 'image.tmdb.org' or parsed.query or parsed.fragment:
                raise ValueError('invalid_image')
    for name in ('year', 'artwork', 'votes'):
        integer(value.get(name, 0), 1_000_000_000)
    for name in ('score', 'popularity'):
        number = value.get(name, 0)
        if type(number) not in (int, float) or not 0 <= number <= 1_000_000_000:
            raise ValueError('invalid_number')
    origins = value.get('origins', [])
    if not isinstance(origins, list) or len(origins) > 30 or any(not isinstance(v, str) or not re.fullmatch(r'[A-Z]{2}', v) for v in origins):
        raise ValueError('invalid_origins')


def validate_changes(body):
    if set(body) != {'changes'} or not isinstance(body['changes'], list) or not 1 <= len(body['changes']) <= 10:
        raise ValueError('invalid_changes')
    seen = set()
    for change in body['changes']:
        if not isinstance(change, dict) or set(change) != {'kind', 'id', 'base_revision', 'mutation_id', 'deleted', 'data'}:
            raise ValueError('invalid_change')
        kind, media_id = change['kind'], change['id']
        if kind not in ('favorite', 'watch') or not isinstance(media_id, str) or not MEDIA_ID.fullmatch(media_id):
            raise ValueError('invalid_identity')
        if (kind, media_id) in seen:
            raise ValueError('duplicate_change')
        seen.add((kind, media_id))
        integer(change['base_revision'])
        if not isinstance(change['mutation_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', change['mutation_id']):
            raise ValueError('invalid_mutation')
        if type(change['deleted']) is not bool or not isinstance(change['data'], dict):
            raise ValueError('invalid_data')
        data = change['data']
        if change['deleted']:
            if data:
                raise ValueError('deleted_payload')
            continue
        allowed = {'media', 'updatedAt'} if kind == 'favorite' else {
            'media', 'updatedAt', 'fid', 'title', 'positionMs', 'durationMs', 'completed',
            'sourceUrl', 'sourceTitle', 'sourceFid', 'isSeries', 'destination', 'topFids'}
        if set(data) - allowed:
            raise ValueError('unknown_field')
        integer(data.get('updatedAt'))
        if kind == 'favorite' or 'media' in data:
            metadata(data.get('media'), media_id)
        if kind == 'watch':
            if not isinstance(data.get('fid'), str) or not FID.fullmatch(data['fid']):
                raise ValueError('invalid_fid')
            text(data.get('title'), 300)
            integer(data.get('positionMs', 0), 604_800_000)
            integer(data.get('durationMs', 0), 604_800_000)
            if type(data.get('completed', False)) is not bool or type(data.get('isSeries', False)) is not bool:
                raise ValueError('invalid_flags')
            if 'sourceUrl' in data:
                text(data['sourceUrl'], 500)
                url = urlsplit(data['sourceUrl'])
                if url.scheme != 'https' or url.netloc != 'pan.quark.cn' or not re.fullmatch(r'/s/[A-Za-z0-9]+/?', url.path) or url.query or url.fragment:
                    raise ValueError('invalid_source')
            if 'sourceTitle' in data:
                text(data['sourceTitle'], 300)
            if 'sourceFid' in data and (not isinstance(data['sourceFid'], str) or not FID.fullmatch(data['sourceFid'])):
                raise ValueError('invalid_source_fid')
        if kind == 'watch' and ('destination' in data or 'topFids' in data):
            if not isinstance(data.get('destination'), str) or not FID.fullmatch(data['destination']):
                raise ValueError('invalid_destination')
            fids = data.get('topFids', [])
            if 'topFids' in data and (not isinstance(fids, list) or not 1 <= len(fids) <= 100 or any(not isinstance(v, str) or not FID.fullmatch(v) for v in fids) or len(set(fids)) != len(fids)):
                raise ValueError('invalid_top_fids')
        if len(json.dumps(data, ensure_ascii=False).encode()) > 10_000:
            raise ValueError('payload_too_large')
    return body['changes']
