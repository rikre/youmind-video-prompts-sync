<div align="center">

# youmind-video-prompts-sync

**把 [YouMind](https://youmind.com/zh-CN/prompts/video) 视频提示词库同步进飞书多维表格 —— 元数据、提示词、互动数据一次搞定。**

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

[English](README.md)

</div>

---

## 它做什么

YouMind 有一个精选的 AI 视频提示词库（Seedance 2.0 / 2.5、Grok Imagine、Claude Opus…）。
这个项目把它镜像进飞书多维表格：

| 字段组 | 内容 |
|---|---|
| 标识 | 标题、提示词 ID、slug、来源板块、模型类型 |
| 作者 | 作者名、作者主页 |
| 素材 | 封面图 URL、视频 URL、视频标题 |
| 内容 | **原始提示词**、中文译文、提示词简介、原始语言 |
| 分类 | 分类标签（32 个类目）、素材类型、是否精选、每周最热 |
| 数据 | 发布时间、**浏览量、点赞量、评论量、分享量、收藏量、引用量** |

它同时是一个 **Agent Skill**（任何读 skill 的 coding agent 都能直接驱动），
也是一组可以挂 cron 的独立脚本。

## 快速开始

```bash
git clone https://github.com/rikre/youmind-video-prompts-sync.git
cd youmind-video-prompts-sync
./install.sh --new-base "YouMind 视频提示词库" --schedule 09:30
```

`install.sh` 会：

1. 把 skill 装进 `~/.agents/skills/youmind-video-prompts-sync/`
2. 新建多维表格（28 个字段）并写好 `~/.youmind-sync/config.json`
3. 注册每天定时任务（只有传了 `--schedule` 才装）

然后跑第一次全量：

```bash
cd ~/.agents/skills/youmind-video-prompts-sync/scripts
python3 sync.py --full                 # 枚举全库 + 抓 Top N 详情页
python3 sync.py --backfill-categories  # 补全分类标签
```

之后 `python3 sync.py` 就是日常增量（约 2–3 分钟）。

### 指向已有的表

```bash
./install.sh --base <base_token> --table <tblxxxxxxxx>
```

## 命令

| 命令 | 作用 | 耗时 |
|---|---|---|
| `sync.py` | 增量：整库扫一遍找新条目 → 抓详情 → 推送 → 翻转「每周最热」 | ~3 分钟 |
| `sync.py --full` | 全量枚举两个库，补齐缺失记录 | ~10 分钟 |
| `sync.py --refresh-top` | 额外刷新各模型 Top N 的互动数据 | +10 分钟 |
| `sync.py --backfill-categories` | 重跑 32 类目反查 | ~10 分钟 |
| `sync.py --dry-run` | 只报告，不碰飞书 | — |
| `sync.py --status` | 打印上次运行结果 | 秒级 |
| `setup_base.sh` | 按 `fields.json` 建表 | — |
| `schedule.sh` | `install [HH:MM]` / `run` / `status` / `logs` / `uninstall` | — |

退出码 `0` = 成功、`1` = 失败，方便定时任务告警。

## 工作方式

```
/youmarketing-api/video-prompts   （POST，可分页的列表接口）
        │  全量元数据：标题、提示词原文、译文、作者、视频、发布日期
        ▼
   按浏览量倒序整库扫描  ──►  每个模型 Top N
        │                          │
        │                          ▼
        │            /zh-CN/video-prompts/{slug}-{id}   （详情页）
        │              JSON-LD interactionStatistic → 浏览 / 点赞 / 评论 / 分享
        │              HTML 数据卡                  → 收藏 / 引用
        │              分类 chip                    → 分类标签
        ▼
   lark-cli base +record-batch-create  ──►  飞书多维表格
```

## 三个一定会踩的坑

1. **不要调高并发。** 接口挂在 Cloudflare 后面，实测 16 并发就把整站封了 58 分钟。
   默认 1.5 请求/秒并带自适应退避（遇 429 降到 0.25/秒）。`SCRAPE_RATE` 不要超过 2。
2. **互动数据默认只抓 Top N。** 列表接口不返回互动指标，每一条都要单独抓详情页。
   默认取每个模型浏览量前 500。要更宽用 `DETAIL_TOP=3000 python3 sync.py --refresh-top`。
3. **没有「只看最新」的廉价增量口子。** 接口会静默忽略 `sortBy=id/createdAt/publishedAt`
   （一律回落到同一个编辑序），而刚发布的提示词浏览量太低、排不进浏览量榜前面。
   所以增量任务会整库扫一遍（约 158 请求 / 2 分钟），而不是只翻第一页。

## 依赖

- `lark-cli`，已登录且具备 `base` + `drive` 权限（`lark-cli auth login --domain base,drive`）
- `python3` ≥ 3.9 且装了 `requests`

## 目录结构

```
.
├── install.sh                     # 一键安装
├── skill/youmind-video-prompts-sync/
│   ├── SKILL.md                   # 给 agent 读的 skill 定义
│   ├── references/
│   │   └── api-and-schema.md      # 接口契约、类目、字段映射、lark-cli 备忘
│   └── scripts/
│       ├── sync.py                # ← 编排器 / 每日入口
│       ├── pipeline.py            # 列表扫描、详情解析、每周最热解析
│       ├── categories.py          # 32 类目反查
│       ├── load.py                # 组行 + 批量写表
│       ├── setup_base.sh          # 建表
│       ├── schedule.sh            # launchd 管理
│       └── fields.json            # 建表 schema（28 字段）
└── docs/
    ├── USAGE-and-prompts.md       # 操作手册 + 可直接粘贴的 agent 提示词
    └── BUILD-NOTES.md             # 抓取过程、字段来源
```

把 `skill/youmind-video-prompts-sync` 整个丢进 `~/.agents/skills/`，agent 就会自动发现它。

## 定时

macOS（`schedule.sh` 自动装）：

```bash
./schedule.sh install 09:30
./schedule.sh status
./schedule.sh logs
```

Linux 用 cron：

```cron
30 9 * * * YOUMIND_DATA_DIR=$HOME/.youmind-sync /usr/bin/python3 $HOME/.agents/skills/youmind-video-prompts-sync/scripts/sync.py
```

## 配置

所有状态都在 `~/.youmind-sync/`（用 `YOUMIND_DATA_DIR` 改）：

| 文件 | 用途 |
|---|---|
| `config.json` | `base_token`、`table_id`、`identity` |
| `state.json` | 已同步 id、每周最热 id、上次运行结果 |
| `prompts_list.jsonl` | 列表接口原始元数据检查点 |
| `prompts_full.jsonl` | 详情页互动数据 + 分类 |
| `categories.json` | id → 分类标签 |
| `sync.log` | 运行日志 |

环境变量：`YOUMIND_DATA_DIR`、`YOUMIND_BASE_TOKEN`、`YOUMIND_TABLE_ID`、
`YOUMIND_IDENTITY`、`SCRAPE_RATE`、`SCRAPE_WORKERS`、`DETAIL_TOP`。

**幂等。** `state.json` 丢了也不怕：同步会先读飞书表里已有的 `提示词ID` 当作已知集合，
不会重复插入。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| 接口返回 `{"error":"Forbidden"}` | 缺 `Origin` / `Referer` 头（脚本已内置） |
| 整站 429，`retry-after` 很大 | Cloudflare 限流。等它过去（脚本会自动轮询），之后把 `SCRAPE_RATE` 调低 |
| `lark-cli ... 91403` | bot 无法访问该表 —— 把 bot 加为协作者，或用 `YOUMIND_IDENTITY=user` 重试一次 |
| 详情页 404 | 提示词已下架；记为 `_httpStatus` 并跳过 |
| 批量写失败 | 每批重试 5 次，仍失败则非 0 退出；重跑会跳过已完成批次 |

## 范围与法律说明

本仓库**只包含代码**，不附带任何抓取到的提示词、作者信息或视频链接 —— 这些内容属于其
原始创作者以及 YouMind / X。使用方式和是否遵守目标站点条款由你自己负责。
请保持克制：默认速率是刻意调慢的。


## 开发

```bash
./scripts/check.sh     # Python/Shell 语法、SKILL.md 清单、敏感串扫描、限速守卫
```

这套检查和 GitHub Actions 跑的是同一套断言。CI 需要 `workflow` OAuth 权限，
而 `gh` 默认登录不带这个 scope，所以 `.github/workflows/ci.yml` 先放在工作区未跟踪，
想启用时执行：

```bash
gh auth refresh --hostname github.com -s workflow
git add .github && git commit -m "ci: add GitHub Actions check" && git push
```

## License

[MIT](LICENSE)
