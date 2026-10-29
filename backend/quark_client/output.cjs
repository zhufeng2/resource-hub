'use strict';

// 命令行只展示允许字段；完整响应可能包含预览地址、令牌等信息。
function fileSummary(item) {
  const fields = [
    'fid',
    'pdir_fid',
    'file_name',
    'file_type',
    'size',
    'format_type',
    'created_at',
    'updated_at',
    'duration',
    'video_width',
    'video_height',
  ];
  return Object.fromEntries(
    fields.filter((key) => Object.hasOwn(item, key)).map((key) => [key, item[key]])
  );
}

function progressSummary(file) {
  const position = file.last_play_info?.time;
  const duration = file.duration;
  const known = typeof position === 'number' && Number.isFinite(position) && position >= 0;
  return {
    fid: file.fid,
    fileName: file.file_name,
    positionSeconds: known ? position : null,
    durationSeconds: duration,
    percent:
      known && duration > 0 ? Math.min(100, Math.round((position / duration) * 10000) / 100) : null,
    recordTimestamp: file.last_play_info?.record_timestamp ?? null,
    listPlayProgress: file.event_extra?.play_progress ?? null,
  };
}

module.exports = { fileSummary, progressSummary };
