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
- `sortBy` **只认 `views`**。`id` / `createdAt` / `publishedAt` 被静默忽略，回落到默认编辑序
  （表现为 `id` 升序的策展顺序），因此不能靠排序做「只看最新」的增量。
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

## 5. lark-cli 命令备忘

```bash
# 建表（--fields 直接吃 fields.json）
lark-cli base +base-create --name "..." --table-name "视频提示词" --fields "$(cat fields.json)" --as bot

# 批量写记录，--json 支持 @file，单批上限 200（脚本用 100）
lark-cli base +record-batch-create --base-token X --table-id T --json @payload.json --as bot --jq .ok

# 读回已有 提示词ID（矩阵格式：data.data + data.fields）
lark-cli base +record-list --base-token X --table-id T --field-id 提示词ID --limit 200 --offset 0 --as bot --format json

# 按条件取 record_id（用于改单条）
lark-cli base +record-list --base-token X --table-id T --filter-json '{"logic":"and","conditions":[["提示词ID","==",11231]]}' --format json

# 同值批量更新
lark-cli base +record-batch-update --base-token X --table-id T --json '{"record_id_list":["rec.."],"patch":{"每周最热":true}}' --as bot --jq .ok
```

注意：`+record-list` 用 `--filter-json`（不是 `--filter`），且 `--jq` 与默认 markdown 输出互斥，
需要 `--format json` 或去掉 `--jq`。
