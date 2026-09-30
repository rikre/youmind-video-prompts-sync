# 抓取与字段说明

记录这套工具的数据来源、字段映射和踩过的坑，方便二次开发。

## 数据规模（一次完整同步的实测值）

| 来源 | 条数 |
|---|---|
| Seedance 2.0 库 | 6,344 |
| Seedance 2.5 库 | 1,530 |
| Grok Imagine 库（默认不同步） | 2,925 |
| 每周最热（可能来自上述之外的模型） | 8 |
| **合计（默认同步前两个库 + 每周最热）** | **7,879** |

互动数据（浏览 / 点赞 / 评论 / 分享 / 收藏 / 引用）默认只覆盖**每个模型浏览量 Top 500**，
共 1,005 条；这批的汇总浏览量约 8,578 万，占全库绝大部分流量。
其余行留空，可用 `DETAIL_TOP=<N> python3 sync.py --refresh-top` 继续补抓。

## 字段来源

| 字段 | 类型 | 来源 |
|---|---|---|
| 标题 | text（主字段） | `prompts[].title` |
| 提示词ID | number | `prompts[].id` |
| Slug | text | `prompts[].slug` |
| 来源板块 | select | 按 model 推导；非库内条目归「每周最热」 |
| 模型类型 | select | `_model`，或详情页 JSON-LD `about.name` |
| 作者 / 作者主页 | text / url | `prompts[].author` |
| 封面图 | url | `videos[0].thumbnail` |
| 视频链接 | url | `videos[0].sourceUrl` |
| 视频标题 | text | `videos[0].caption` |
| 详情页链接 | url | 拼装 `/zh-CN/video-prompts/{slug}-{id}` |
| 原始来源推文 | url | `prompts[].sourceLink` |
| 提示词简介 | text | `prompts[].description` |
| 原始提示词 | text | `prompts[].content` |
| 中文译文 | text | `translatedContent`（原文已是中文时留空） |
| 原始语言 | select | `language` 归一化为 zh/en/ja/ko/other |
| 分类标签 | select(multiple) | 32 个类目，来自详情页 chip 或类目反查 |
| 发布时间 | datetime | `sourcePublishedAt` + 8h（Base 时区） |
| 浏览量/点赞量/评论量/分享量 | number | 详情页 JSON-LD `interactionStatistic` |
| 收藏量/引用量 | number | 详情页 HTML 数据卡（JSON-LD 里没有） |
| 素材类型 | select | 有 `sourceUrl` → 视频；有缩略图 → 图片；否则无素材 |
| 是否精选 | checkbox | `prompts[].featured` |
| 每周最热 | checkbox | 落地页快照，每轮同步会翻转 |
| 入库时间 | created_at | 系统字段，不写 |

## 数据源

接口契约的单一事实来源是
[../skill/youmind-video-prompts-sync/references/api-and-schema.md](../skill/youmind-video-prompts-sync/references/api-and-schema.md)。
要点：

- 列表接口 `POST /youmarketing-api/video-prompts`，必须带 `Origin` + `Referer`，`limit` 上限 50。
- 分类归属只能通过 `videoCategoryFilters` 按 32 个类目逐个反查（`categories.py`），
  比抓 7,874 个详情页快一个数量级。
- 互动数据只在详情页；`--compressed` 后每页约 76 KB。

## 坑

### 1. Cloudflare 整站限流

突发并发代价极高：实测 16 并发、15 秒后整站返回 `429` 并附
`retry-after: 3488`（约 58 分钟）。期间列表接口和详情页全部不可用。

现在的做法：

- 全局令牌桶限速，默认 1.5 请求/秒（`SCRAPE_RATE`）
- 遇到 429 自动把速率乘 0.6（下限 0.25/秒）并指数退避，最多等 600 秒
- 启动前先探测站点可达性，被限流就轮询等待

**不要把 `SCRAPE_RATE` 调到 2 以上，也不要加并发。**

### 2. 没有「按最新排序」的接口

`sortBy` 只认 `views`。传 `id` / `createdAt` / `publishedAt` 不会报错，而是**静默回落到默认编辑序**
（表现得像 id 升序的策展顺序）。所以：

- 想找新发布的提示词，没有廉价入口，必须整库扫一遍（158 请求 / 约 2 分钟）
- 按 views 扫还有个副作用：抓取期间浏览量变化会让条目在页间漂移，理论上可能漏条。
  实测一次 127 页的扫描没有出现重复或缺失，但这是概率问题，不是保证。
  想更稳就降低速率（漂移窗口更小）。

### 3. 时区

源数据 `sourcePublishedAt` 是 UTC，飞书 Base 时区是 `+08:00`。
写入前统一 `+8h` 并格式化成本地时间字符串，否则表格里会整体偏 8 小时。

### 4. 长文本

`content` 最长实测 8,912 字符，`translatedContent` 最长 12,070 字符，都在单格限制内。
`load.py` 里的 `MAX_TEXT = 60000` 是安全阀，超过会截断并计数。

### 5. 幂等

`load.push()` 按「本次新增 id 集合」的哈希命名推送日志（`pushed_<hash>.txt`），
同一批重跑不会重复插入。`state.json` 丢失时会先读飞书表里已有的 `提示词ID` 重建已知集合。

## 关于数据

本仓库**不包含**任何抓取结果。作者本地保存的离线快照（`records.json`、
`records.csv.gz` 等）属于 YouMind / X 上的第三方内容，不随仓库分发。
