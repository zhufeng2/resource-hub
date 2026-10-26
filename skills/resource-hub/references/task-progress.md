# 任务接续与验收

系列请求固定一个 task 名称；不同任务名称隔离覆盖清单，近期同一分享的核验结果仍可复用。任务保存在本机缓存目录的 progress.sqlite3，不存账号密码或访问 token。删除该文件会丢失任务进度；不会操作网盘。旧版结果不会自动导入，首次使用新版本需重新建立任务。

## MCP 搜索与接续

以同一任务名称在对话或工作区 JSON 记录覆盖清单和搜索进度：每个关键词保存 query、request_id、search_id、固定分页大小 20、下一页原始 offset、has_more，候选按 URL 去重，记录来源、提取码、内容核验和待办。不要保存 MCP Token、网页 Cookie 或分享访问令牌。

搜索使用 MCP `search_resources`，翻页使用 `get_search_results`。初次搜索后的下一页 offset 为 20，此后按固定窗口加 20；剔除失效链接会缩短返回列表，不能按列表长度递增 offset。空页但 has_more=true 时继续下一窗口。超时重试同一搜索复用 request_id；换词或重新搜索生成新 ID。读取已有结果不扣新额度，记录有效期为 24 小时。

MCP 搜索记录不会自动导入旧 progress.sqlite3 候选队列；不要执行旧 `resource.py search` 来接续 MCP 任务。可以在任务 JSON 中保留全部搜索与分页信息，使用下方本地 progress 命令单独维护覆盖、官方核验和实际保存证据。该命令不调用搜索接口。

```sh
python3 "<skill>/scripts/resource.py" progress --task '本次系列补齐'
```

已核验目录复用其证据；有疑问或待展开目录使用夸克官方 share-detail，再记录结果。metadata_observed 只表示读到文件，不表示匹配。已有候选仍无法满足目标时才查有依据的别名；不因缓存超时或结果数量稳定推断全网完整。

## 记录覆盖、转存与官方核验

将实际证据整理成 JSON 文件，通过以下命令更新。coverage 和 saved 是整个数组的替换，先读取并保留已有条目；verified 逐条更新核验缓存。MCP 查询及分页信息保存在任务 JSON 中，不要传入 --record；该参数仅接受 coverage、saved、verified。

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
```

离线测试覆盖保留脚本的兼容性，使用临时目录与模拟响应，不读取真实凭据、不操作网盘。MCP 连接通过 `get_quota` 验证；搜索链路需要一次真实 `search_resources`，成功会计次，再用返回的 search_id 验证读取。不要运行旧 auth-test 检查 MCP。连接成功、搜索成功、内容匹配和转存成功分别报告。
