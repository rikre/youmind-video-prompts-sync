# YouMind 接口与飞书字段参考

## 1. 列表接口

```
POST https://youmind.com/youmarketing-api/video-prompts
Content-Type: application/json
Origin:  https://youmind.com
Referer: https://youmind.com/zh-CN/seedance-2-0-prompts/explore
```

请求体：

```json
{
  "model": "seedance-2.0",
  "page": 1,
  "limit": 50,
  "locale": "zh-CN",
  "sortBy": "views",
  "sortOrder": "desc",
  "reviewedOnly": false,
  "videoCategoryFilters": {"subjects": [113]}
}
```

- `limit` 实际上限 50，传更大也只回 50 条。
- `model`：`seedance-2.0`（6344）、`seedance-2.5`（1530）、`grok-imagine`（2925）。
- `sortBy` 认 **`views`** 和 **`publishedAt`**；`id` / `createdAt` 被静默忽略，回落到默认编辑序
  （表现得像策划顺序）。

#### `sortBy=publishedAt&sortOrder=desc` 的实际形态（实测）

```
page 1  条 0-5   2026-02-11 .. 2026-04-02   ← featured 置顶块，日期是老的
page 1  条 6-49  2026-09-30 .. 2026-09-23   ← 从这里开始严格按发布时间倒序
page 2           2026-09-23 .. 2026-09-13
page 3           2026-09-13 .. 2026-09-08
page 20          2026-07-29 .. 2026-07-31
page 60          2026-05-28 .. 2026-05-29
page 120         2026-02-19 .. 2026-02-22
```

结论：**存在廉价的「只看最新」入口**，但停止条件不能写成「本页最早的一条比水位老」——
第 1 页带着 6 条老日期的置顶项，那条规则会在第 1 页就误停。
正确规则是：**只要本页还有任何一条比水位新，就继续翻页；某一页全都不比水位新时停止。**
安静的一天 = 1～2 个请求。
- `videoCategoryFilters` 的 key 是三个维度：`useCases` / `styles` / `subjects`，
  值是类目 id 数组。这是**唯一**能批量拿到分类归属的入口。
- 缺失 `Origin`/`Referer` 会返回 `{"error":"Forbidden"}`。

响应：

```json
{
  "prompts": [{
    "id": 1402, "title": "...", "description": "...", "slug": "japanese-classroom-romance",
    "featured": true, "content": "<原文>", "language": "zh",
    "translatedContent": "<该 locale 的译文>",
    "sourceLink": "https://x.com/...", "sourcePublishedAt": "2026-03-15T09:55:41.000Z",
    "author": {"name": "...", "link": "https://x.com/..."},
    "videos": [{"sourceUrl": "...", "thumbnail": "...", "caption": "...", "sourceType": "media"}]
  }],
  "total": 6344, "page": 1, "limit": 50, "totalPages": 127, "hasMore": true
}
```

`content` 是原文；`language == "zh"` 时 `translatedContent` 与原文高度重复，写表时留空即可。

## 2. 详情页

```
GET https://youmind.com/zh-CN/video-prompts/{slug}-{id}        # 无 slug 时退化为 /{id}
```

页面里有两块结构化数据：

1. `<script type="application/ld+json">` 的 `@graph`
   - `CreativeWork.interactionStatistic` → LikeAction / ViewAction / CommentAction / ShareAction
   - `CreativeWork.text` 原文提示词、`author`、`datePublished`、`inLanguage`、`isBasedOn`（原推文）
   - `VideoObject.contentUrl` 视频地址、`thumbnailUrl` 封面
2. 六宫格数据卡（HTML）→ 点赞 / 浏览 / 分享 / 评论 / **收藏** / **引用**
   后两项 JSON-LD 里没有，只能从 HTML 抓。

分类标签在 `href="...?categories=<slug>"` 的 chip 上。

详情页约 390KB，`--compressed` 后 ~76KB。

## 3. 类目

三个维度共 32 个类目（`categories.py` 里是 SSOT）：

| 维度 key | parentSlug | 类目 id | 数量 |
|---|---|---|---|
| `useCases` | video-use-cases | 87–95 | 9 |
| `styles` | video-styles | 96–106 | 11 |
| `subjects` | video-subjects | 107–118 | 12 |

## 4. 飞书多维表格字段（`scripts/fields.json`）

| 字段 | 类型 | 来源 |
|---|---|---|
| 标题 | text（主字段） | `prompts[].title` |
| 提示词ID | number | `prompts[].id` |
| Slug | text | `prompts[].slug` |
| 来源板块 | select | 按 model 推导；非库内条目归「每周最热」 |
| 模型类型 | select | `_model` 或 JSON-LD `about.name` |
| 作者 / 作者主页 | text / url | `prompts[].author` |
| 封面图 | url | `videos[0].thumbnail` |
| 视频链接 | url | `videos[0].sourceUrl` |
| 视频标题 | text | `videos[0].caption` |
| 详情页链接 | url | 拼装 |
| 原始来源推文 | url | `prompts[].sourceLink` |
| 提示词简介 | text | `prompts[].description` |
| 原始提示词 | text | `prompts[].content` |
| 中文译文 | text | `translatedContent`（语言为 zh 时留空） |
| 原始语言 | select | `language` 归一化为 zh/en/ja/ko/other |
| 分类标签 | select(multiple) | 32 类目 |
| 发布时间 | datetime | `sourcePublishedAt` + 8h |
| 浏览量/点赞量/评论量/分享量/收藏量/引用量 | number | 详情页 |
| 素材类型 | select | 视频 / 图片 / 无素材 |
| 是否精选 | checkbox | `prompts[].featured` |
| 每周最热 | checkbox | 落地页「每周最热」快照，每轮同步会翻转 |
| 入库时间 | created_at | 系统字段，不写 |

CellValue 约定：文本/URL 用字符串；数字用 JSON number（不要千分位）；
多选用数组；checkbox 用 `true`/`false`；日期用 `"YYYY-MM-DD HH:mm:ss"` 字符串。
`入库时间` 是只读系统字段，写入会被忽略。

## 4.5 多租户与 wiki 链接

目标多维表格不一定在当前默认 app 的租户里。`lark-cli profile list` 能看到本机所有 profile；
调用时加 `--profile <名字或 appId>`。

wiki 链接（`https://<tenant>.feishu.cn/wiki/<node>?table=...`）里的 token 是 **wiki node token**，
不是 base token，必须先解析：

```bash
lark-cli --profile <p> base +url-resolve --url "<wiki 链接>" --as bot
# → {"base_token": "...", "block_id": "tbl...", "block_name": "视频提示词"}
```

`base_token` 拿去当 `--base-token`，`block_id` 拿去当 `--table-id`。
跨租户时 bot 会返回 `131006 bot lacks permission`，换 profile 或让表主人把 app 加为协作者。

## 5. lark-cli 命令备忘

```bash
# 建表（--fields 直接吃 fields.json）
lark-cli base +base-create --name "..." --table-name "视频提示词" --fields "$(cat fields.json)" --as bot

# 指定 profile（跨租户时必须）
lark-cli --profile dashboard-bollo base +record-list --base-token X --table-id T --as bot

# 批量写记录，--json 支持 @file，单批上限 200（脚本用 100）
# 注意：@file 只允许 CWD、/tmp、~/files 三个根；macOS 的 tempfile.gettempdir()
# 返回 /var/folders/... 会被拒，所以脚本固定写 /tmp
lark-cli base +record-batch-create --base-token X --table-id T --json @payload.json --as bot --jq .ok

# 读回已有 提示词ID（矩阵格式：data.data + data.fields）
lark-cli base +record-list --base-token X --table-id T --field-id 提示词ID --limit 200 --offset 0 --as bot --format json

# 按条件取 record_id（用于改单条）
lark-cli base +record-list --base-token X --table-id T --filter-json '{"logic":"and","conditions":[["提示词ID","==",11231]]}' --format json

# 同值批量更新
lark-cli base +record-batch-update --base-token X --table-id T --json '{"record_id_list":["rec.."],"patch":{"每周最热":true}}' --as bot --jq .ok
```

注意：

- `+record-list` 用 `--filter-json`（不是 `--filter`），且 `--jq` 与默认 markdown 输出互斥，
  需要 `--format json` 或去掉 `--jq`。
- `data-query` 的 `MAX(发布时间)` 会把 datetime 当**秒**返回，格式化出来是 1970 年。
  要拿最新时间就用 `+record-list --sort-json '[{"field":"发布时间","desc":true}]' --limit 1`。
- `@file` 形式的 `--json` 只允许 CWD、`/tmp`、`~/files` 三个根目录。
