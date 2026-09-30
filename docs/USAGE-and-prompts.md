# 操作手册 & Agent 提示词

## 一、安装

```bash
git clone https://github.com/rikre/youmind-video-prompts-sync.git
cd youmind-video-prompts-sync
./install.sh --new-base "YouMind 视频提示词库" --schedule 09:30
```

`install.sh` 做三件事：

1. 把 skill 装到 `~/.agents/skills/youmind-video-prompts-sync/`
2. 新建多维表格（28 个字段）并写好 `~/.youmind-sync/config.json`
3. 注册 launchd 定时任务（只有传 `--schedule` 才装）

其它用法：

```bash
./install.sh                                              # 只装 skill，不建表不装定时
./install.sh --base <token> --table <tblxxx>              # 指向已有表
./install.sh --new-base "我的提示词库" --schedule 09:30    # 建新表 + 定时
./install.sh --uninstall                                  # 卸载（数据保留）
```

首次全量：

```bash
cd ~/.agents/skills/youmind-video-prompts-sync/scripts
python3 sync.py --full
python3 sync.py --backfill-categories
```

## 二、日常操作

```bash
cd ~/.agents/skills/youmind-video-prompts-sync/scripts

./schedule.sh status          # 定时任务是否在跑 + 上次结果
./schedule.sh run             # 不等定时，立刻同步一次
./schedule.sh logs            # 看最近日志
./schedule.sh install 08:00   # 换时间，会覆盖旧任务
./schedule.sh uninstall       # 卸掉定时任务

python3 sync.py --status      # 看同步状态（秒级）
python3 sync.py --dry-run     # 只报告不写飞书
python3 sync.py               # 手动增量（约 3 分钟）
python3 sync.py --refresh-top # 顺便刷新各模型 Top 500 的互动数据
python3 sync.py --full        # 全量枚举 + 补齐缺失记录
python3 sync.py --backfill-categories   # 重跑 32 类目反查
```

日志：`~/.youmind-sync/sync.log`，退出码 `0` = 成功、`1` = 失败。

## 三、Agent 提示词

下面四段可以直接粘给任何读 skill 的 coding agent。

### ① 日常增量（最常用）

```
同步一下 YouMind 视频提示词库，把新增的提示词写进飞书多维表格
```

### ② 全新环境从零建表

```
使用 youmind-video-prompts-sync skill，帮我做一套 YouMind 视频提示词库的飞书多维表格同步：

1. 先跑 scripts/setup_base.sh 新建多维表格，字段用 scripts/fields.json
   （28 个字段：标题/作者/封面/视频/原始提示词/中文译文/模型类型/发布时间/
   分类标签/浏览量/点赞量/评论量/分享量/收藏量/引用量 等）
2. 然后 python3 sync.py --full 全量灌数据，再 python3 sync.py --backfill-categories 补分类
3. 最后 ./schedule.sh install 09:30 注册每天自动增量

注意事项：
- youmarketing-api 有 Cloudflare 限流，SCRAPE_RATE 不要超过 1.5，也别加并发
- 如果整站返回 429，等 retry-after 过去再跑，脚本自己会轮询等待
- 跑完把表格链接、总记录数、本次新增条数告诉我
```

### ③ 只做增量 + 汇报（适合放进别的自动化）

```
用 youmind-video-prompts-sync skill 跑一次增量同步，然后只汇报：
本次新增多少条、写入了哪些标题、飞书表格当前总记录数、有没有报错。
不要做全量重扫，不要动已有的记录。
```

### ④ 换表 / 扩模型范围

```
把 YouMind 提示词同步的目标表换成 <新表链接>，并把抓取范围改成
Seedance 2.0 + Seedance 2.5 + Grok Imagine 三个模型，Top 500 互动数据照旧。
改完跑一次 --full 验证。
```

> 扩模型范围需要改两个地方：`pipeline.py` 的 `MODELS` 列表，
> 以及 `categories.py` 的 `MODELS`。`grok-imagine` 的 model key 已实测可用。

## 四、注意事项

- **互动数据默认只覆盖每个模型浏览量 Top 500**（共 1,005 条）。列表接口不返回互动指标，
  必须逐条抓详情页；要更宽就 `DETAIL_TOP=3000 python3 sync.py --refresh-top`。
- **别调高并发。** 实测 16 并发 15 秒就被 Cloudflare 整站封 58 分钟。
- **幂等。** `~/.youmind-sync/state.json` 丢了也不怕，会先读飞书表里已有的 `提示词ID`
  当作已知集合，不会重复写入。
- **每周最热会翻转**：每轮同步会把不再是热门的条目取消勾选。
- **增量要整库扫一遍**（约 2 分钟）：接口静默忽略 `sortBy=id/createdAt/publishedAt`，
  新提示词浏览量低、排不到前面。
- **Linux** 用 cron 替代 launchd：

  ```cron
  30 9 * * * YOUMIND_DATA_DIR=$HOME/.youmind-sync /usr/bin/python3 $HOME/.agents/skills/youmind-video-prompts-sync/scripts/sync.py
  ```
