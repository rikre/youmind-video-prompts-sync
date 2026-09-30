---
name: youmind-video-prompts-sync
description: 抓取 YouMind 视频提示词库（Seedance 2.0 / 2.5 全量 + 每周最热）并同步到飞书多维表格，包含作者、封面、视频、原始提示词、中文译文、模型类型、发布时间、分类标签，以及浏览量/点赞/评论/分享/收藏/引用等互动数据。当用户说「同步 YouMind 提示词」「更新视频提示词表」「抓 youmind.com/zh-CN/prompts/video」「提示词库增量同步」「新建一个提示词多维表格」，或需要为这类抓取配置定时任务时使用。
---

# YouMind 视频提示词 → 飞书多维表格

把 [youmind.com/zh-CN/prompts/video](https://youmind.com/zh-CN/prompts/video) 的视频提示词库
同步进飞书多维表格：全量元数据 + 热门条目的互动数据。

## 关键事实（先读，能省很多时间）

- **数据源不是 HTML 抓取。** 列表走公开 POST 接口
  `https://youmind.com/youmarketing-api/video-prompts`，请求体
  `{model, page, limit, locale, sortBy, sortOrder, reviewedOnly}`，`model` 取值
  `seedance-2.0`（6344 条）、`seedance-2.5`（1530 条）、`grok-imagine`（2925 条）。
  必须带 `Origin: https://youmind.com` 和 `Referer: https://youmind.com/zh-CN/seedance-2-0-prompts/explore`，否则 403。
  `limit` 上限 50（传更大也只返回 50）。
- **列表接口不返回互动数据。** 浏览量/点赞/评论/分享/收藏/引用只存在于详情页
  `/zh-CN/video-prompts/{slug}-{id}` 的 JSON-LD（`interactionStatistic`）和页面里的 收藏/引用 角标。
  全量 7874 页太贵，默认只抓**每个模型浏览量 Top 500**（共 ~1005 页），已覆盖绝大部分流量。
- **分类标签**只出现在详情页；但列表接口支持 `videoCategoryFilters: {useCases|styles|subjects: [id]}`，
  逐个类目反查 32 次就能拿到全量 id→分类映射（`categories.py`，约 10 分钟，远快于抓 7874 个详情页）。
- **排序**：`sortBy` 认 `views` 和 `publishedAt`；`id` / `createdAt` 会被静默忽略并回落到默认编辑序。
  `publishedAt desc` 从**第 1 页第 7 条起**严格按发布时间倒序，所以有廉价的「只看最新」入口 ——
  注意第 1 页前几条是 `featured` 置顶块，带的是老日期，判断「本页是否还有更新的」不能看页内最早一条，
  要看**是否存在任何一条比水位新**。安静的一天只要 1～2 个请求。
- **多租户**：目标表可能不在当前默认 app 的租户里。用 `YOUMIND_PROFILE=<lark-cli profile>`（或
  config.json 的 `profile` 字段）切到对应租户的 app，脚本会给每个 lark-cli 调用加 `--profile`。
  `lark-cli profile list` 可以看到本机所有 profile。
- **Cloudflare 限流是最大的坑。** 突发并发会让整站 429 约 1 小时（实测 16 并发 15 秒即被封 58 分钟）。
  脚本内置自适应限流：默认 1.5 请求/秒，遇到 429 自动把速率降到 0.25/秒 并长退避。
  **不要把 `SCRAPE_RATE` 调到 3 以上。**
- 发布时间源数据是 UTC，飞书 Base 时区是 +08:00，写入前统一 +8 小时。

## 依赖

- `lark-cli` 已登录且具备 `base` 域权限；默认用 `--as bot`（bot 建的表会自动给当前 CLI 用户 full_access）。
  仅当 bot 无权访问目标表时才改用 `--as user`。
- `python3` + `requests`。

## 快速开始

```bash
# 0) 装到 skills 目录（可选，装完可被 agent 自动发现）
cp -R <skill目录> ~/.agents/skills/

# 1) 新建一张多维表格（28 个字段），并把 base_token 写进 ~/.youmind-sync/config.json
cd ~/.agents/skills/youmind-video-prompts-sync/scripts
./setup_base.sh "YouMind 视频提示词库"

# 2) 首次全量灌数据（枚举 7874 条 + 抓 Top 500 详情 + 全量分类映射，约 25 分钟）
python3 sync.py --full
python3 sync.py --backfill-categories

# 3) 之后的日常增量（约 3 分钟）
python3 sync.py
```

已有表时跳过第 0/1 步，直接写 `~/.youmind-sync/config.json`：

```json
{"base_token": "xxxx", "table_id": "tblxxxx", "identity": "bot", "profile": "", "window_days": 1}
```

- `profile`：目标表在别的租户时，填 `lark-cli profile list` 里的 profile 名或 appId。
  知识库（wiki）链接要先 `lark-cli base +url-resolve --url "<wiki 链接>"` 解析出真正的
  `base_token` / `table_id`，不能把 wiki token 当 base token 用。
- `window_days`：时间窗口往回多留几天（默认 1），防止跨时区/延迟导致漏条。

## sync.py 子命令

| 命令 | 作用 | 耗时 |
|---|---|---|
| `sync.py` | **默认增量**：读表里最新的发布时间当水位，只扫这个时间之后的提示词 | **~6 秒**（预热后） |
| `sync.py --since 2026-09-01` | 指定起始日期 | 秒级 |
| `sync.py --since 7d` | 最近 7 天 | 秒级 |
| `sync.py --sweep-all` | 不用时间，按浏览量整库扫一遍找新条目（兜底） | ~2 分钟 |
| `sync.py --full` | 全量枚举 + 补齐 Base 中缺失的记录 | ~10 分钟 |
| `sync.py --refresh-top` | 额外刷新各模型 Top N 的互动数据 | +10 分钟 |
| `sync.py --backfill-categories` | 重跑 32 类目反查，补全分类标签 | ~10 分钟 |
| `sync.py --dry-run` | 只报告不写飞书 | — |
| `sync.py --status` | 打印上次运行结果 | 秒 |

退出码 0 = 成功，1 = 失败（定时任务据此告警）。日志：`~/.youmind-sync/sync.log`。

**时间水位怎么算**：取表里 `发布时间` 的最大值（读 1 条排序结果，不用 data-query 的 MAX ——
它把 datetime 当秒返回，格式化会变成 1970），减去 `window_days` 天（默认 1）作为窗口起点。
窗口内再按 `提示词ID` 去重。首次运行（`state.json` 不存在）会先花 ~40 秒从表里读回已知 ID，
之后每轮就是几秒。

## 数据与状态

全部落在 `~/.youmind-sync/`（用 `YOUMIND_DATA_DIR` 覆盖）：

| 文件 | 内容 |
|---|---|
| `state.json` | `synced_ids` / `weekly_ids` / 上次运行结果 |
| `prompts_list.jsonl` | 列表接口全量元数据（首次运行自动从 `.gz` 展开） |
| `prompts_full.jsonl` | 详情页互动数据 + 分类 |
| `categories.json` | id → 分类标签映射 |
| `weekly.json` / `weekly.html` | 本次的「每周最热」快照 |
| `pushed_<hash>.txt` | 推送日志，按「本次新增 id 集合」哈希命名，重跑同一批不会重复写入 |
| `sync.log` | 运行日志 |

**幂等性**：`state.json` 缺失时会自动读 Base 里已存在的 `提示词ID` 作为已知集合，所以删掉本地状态也不会重复灌数据。

## 定时任务（macOS / launchd）

```bash
./schedule.sh install 09:30   # 每天 09:30 跑一次（默认就是这个时间）
./schedule.sh run             # 立刻跑一次
./schedule.sh status          # 是否已加载 + 上次结果
./schedule.sh logs            # 看最近日志
./schedule.sh uninstall
```

launchd 的 PATH 很干净，`schedule.sh` 会把 python3 和 `lark-cli` 所在目录钉进 plist。
Mac 在计划时间处于睡眠状态时，launchd 会在唤醒后补跑。

Linux 用 cron 替代：

```cron
30 9 * * * YOUMIND_DATA_DIR=$HOME/.youmind-sync /usr/bin/python3 $HOME/.agents/skills/youmind-video-prompts-sync/scripts/sync.py >> $HOME/.youmind-sync/cron.log 2>&1
```

## 字段结构

建表用的 schema 在 `scripts/fields.json`（28 个字段，`+base-create --fields` 直接吃）。
主字段 `标题`；`分类标签` 是 32 项多选；`每周最热` / `是否精选` 是 checkbox；
封面图 / 视频链接 / 详情页链接 / 作者主页 / 原始来源推文 是 URL 文本字段。
细节见 [references/api-and-schema.md](references/api-and-schema.md)。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| 接口返回 `{"error":"Forbidden"}` | 缺 `Origin` / `Referer` 头 |
| 整站 429，`retry-after` 上千秒 | 触发了 Cloudflare 限流。等它过去（脚本会自动轮询），下次把 `SCRAPE_RATE` 降到 1.0 |
| `lark-cli ... 91403` | bot 无该表权限。把 bot 加为协作者，或 `YOUMIND_IDENTITY=user` 重试一次 |
| 详情页 404 | 该提示词已下架；脚本记录 `_httpStatus` 并跳过，不阻塞整批 |
| 推送批量失败 | 脚本每批重试 5 次，仍失败会非 0 退出；重跑会自动跳过已成功批次 |
| `--json invalid JSON file path ... outside the built-in allowlist` | lark-cli 只接受 CWD / `/tmp` / `~/files` 下的 `@file`；脚本已固定把批次写到 `/tmp`（注意 macOS 的 `tempfile.gettempdir()` 是 `/var/folders/...`，会被拒） |
| `131006 bot lacks permission for the requested resource` | app 与目标表不在同一租户，或表没共享给该 app。换 `profile`，或把 app 加为文档协作者 |
