# 任务接续与验收

系列请求固定一个 task 名称；不同任务名称隔离覆盖清单，近期同一分享的核验结果仍可复用。任务保存在本机缓存目录的 progress.sqlite3，不存账号密码或访问 token。删除该文件会丢失任务进度；不会操作网盘。旧版结果不会自动导入，首次使用新版本需重新建立任务。

## 搜索与接续

```sh
python3 "<skill>/scripts/resource.py" search '正式名称' --task '本次系列补齐' --search-only
python3 "<skill>/scripts/resource.py" search '英文别名' --task '本次系列补齐' --search-only
python3 "<skill>/scripts/resource.py" search '正式名称' --task '本次系列补齐'
python3 "<skill>/scripts/resource.py" search '正式名称' --task '本次系列补齐' --recheck
python3 "<skill>/scripts/resource.py" progress --task '本次系列补齐'
```

有 pending_urls 时继续同一任务；有 official_pending_urls 时使用夸克官方 share-detail，再记录结果。metadata_observed 只表示读到文件，不表示匹配。查完已有候选仍有缺项时换有依据的别名；不要无限重复不变的请求。

服务不提供最终状态字段时 completeness=unknown。不能根据结果数量稳定或某个缓存超时推断完整；客户端只合并实际拿到的结果。来源过滤异常需结合后端日志排查，不能通过客户端承诺修复。

## 记录覆盖、转存与官方核验

将实际证据整理成 JSON 文件，通过以下命令更新。coverage 和 saved 是整个数组的替换，先读取并保留已有条目；verified 逐条更新核验缓存。查询候选合并是事务操作，不会因并发搜索丢失别名结果。核验流程串行运行。

```sh
python3 "<skill>/scripts/resource.py" progress --task '本次系列补齐' --record '本地记录.json'
```

示例结构（把示例改成实际作品、来源与官方结果后再写入）：

```json
{
  "coverage": [{"series": "作品名", "expected_episodes": 6, "missing": [5], "source_url": "正式作品页地址"}],
  "saved": [{"path": "AI转存/作品名", "task_id": "官方任务ID", "task_status": "success", "directory_verified": true}],
  "verified": [{
    "url": "https://pan.quark.cn/s/实际分享ID",
    "password": "",
    "content_status": "metadata_observed",
    "content": {"listing_complete": false, "files": [{"name": "实际文件名.mp4", "path": "相关目录/实际文件名.mp4", "size": 123, "is_video": true}]}
  }]
}
```

content_status 可为 metadata_observed、empty、unavailable。empty 要求完整枚举且文件列表为空；unavailable 仅用于官方明确失效，网络报错不能这样记录。官方访问 token 不得写入记录文件。记录只保存证据，不执行转存、不自动宣称作品完整。已转存文件取得官方成功终态后即可更新 saved；仅在实际查过目标目录时记录 `directory_verified: true`，没有查过则省略该字段或记为 false，不为填满记录追加非必要查询。

## 回归检查

```sh
python3 "<skill>/tests/test_workflow.py" -v
python3 "<skill>/scripts/resource.py" auth-test
```

离线测试使用临时目录与模拟响应，不读取真实凭据、不操作网盘。auth-test 会读取本机配置，绕过旧登录缓存并做一次真实搜索权限验证；不会转存文件。新配置验证成功与文件可播放是不同结论。
