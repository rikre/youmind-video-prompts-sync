<div align="center">

# youmind-video-prompts-sync

**Scrape the [YouMind](https://youmind.com/zh-CN/prompts/video) video-prompt library and keep a
Feishu / Lark Bitable in sync — metadata, prompts, and engagement stats.**

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#scheduling)

[中文说明](README.zh-CN.md)

</div>

---

## What it does

YouMind publishes a curated library of AI video prompts (Seedance 2.0 / 2.5, Grok Imagine,
Claude Opus…). This project mirrors it into a Feishu Bitable:

| Field group | Contents |
|---|---|
| Identity | title, prompt id, slug, source section, model |
| Author | name, profile URL |
| Media | cover image URL, video URL, video caption |
| Content | **original prompt**, Chinese translation, summary, original language |
| Taxonomy | category tags (32 categories), material type, featured flag, weekly-hot flag |
| Stats | published date, **views, likes, comments, shares, bookmarks, quotes** |

It ships as an [Agent Skill](https://github.com/rikre/youmind-video-prompts-sync) that any
coding agent can drive, plus standalone scripts you can cron.

## Quick start

```bash
git clone https://github.com/rikre/youmind-video-prompts-sync.git
cd youmind-video-prompts-sync
./install.sh --new-base "YouMind video prompts" --schedule 09:30
```

`install.sh` will:

1. copy the skill into `~/.agents/skills/youmind-video-prompts-sync/`
2. create the Bitable (28 fields) and write `~/.youmind-sync/config.json`
3. register a daily launchd job (only when you pass `--schedule`)

Then run the first full sync:

```bash
cd ~/.agents/skills/youmind-video-prompts-sync/scripts
python3 sync.py --full                 # enumerate everything + top-N detail pages
python3 sync.py --backfill-categories  # fill category tags for every row
```

After that, `python3 sync.py` is the daily incremental (about 2–3 minutes).

### Point at an existing Bitable

```bash
./install.sh --base <base_token> --table <tblxxxxxxxx>
```

## Commands

| Command | What it does | Cost |
|---|---|---|
| `sync.py` | incremental: sweep for new prompts → fetch details → push → rotate the weekly-hot flag | ~3 min |
| `sync.py --full` | enumerate both libraries, push everything missing | ~10 min |
| `sync.py --refresh-top` | also refresh engagement stats for the top N per model | +10 min |
| `sync.py --backfill-categories` | re-run the 32-category reverse lookup | ~10 min |
| `sync.py --dry-run` | report only, never touch the Bitable | — |
| `sync.py --status` | print the last run summary | instant |
| `setup_base.sh` | create the Bitable + fields from `fields.json` | — |
| `schedule.sh` | `install [HH:MM]` / `run` / `status` / `logs` / `uninstall` | — |

Exit code `0` = success, `1` = failure, so a scheduler can alert on it.

## How it works

```
/youmarketing-api/video-prompts   (POST, paginated list API)
        │  full metadata: title, prompt text, translation, author, video, date
        ▼
   views-desc sweep  ──►  top N per model
        │                        │
        │                        ▼
        │            /zh-CN/video-prompts/{slug}-{id}   (detail page)
        │              JSON-LD interactionStatistic → views / likes / comments / shares
        │              HTML stat cards              → bookmarks / quotes
        │              category chips               → tags
        ▼
   lark-cli base +record-batch-create  ──►  Feishu Bitable
```

## Three things that will bite you

1. **Do not raise concurrency.** The API sits behind Cloudflare; 16 parallel requests got the
   whole zone 429'd for ~58 minutes in testing. The default is 1.5 req/s with adaptive
   back-off (drops to 0.25 req/s on 429). Keep `SCRAPE_RATE` ≤ 2.
2. **Engagement stats are Top-N only by default.** The list API does not return them; each one
   costs a detail-page fetch. Default is the 500 most-viewed per model. Go wider with
   `DETAIL_TOP=3000 python3 sync.py --refresh-top`.
3. **There is no cheap "newest first" feed.** The API silently ignores
   `sortBy=id/createdAt/publishedAt` (they all fall back to the same editorial order), and a
   freshly published prompt has too few views to reach the head of the views ranking. So the
   incremental job sweeps the whole library (~158 requests / ~2 min) instead of paging once.

## Requirements

- `lark-cli`, authenticated with the `base` + `drive` scopes
  (`lark-cli auth login --domain base,drive`)
- `python3` ≥ 3.9 with `requests`

## Repo layout

```
.
├── install.sh                     # one-shot installer
├── skill/youmind-video-prompts-sync/
│   ├── SKILL.md                   # agent-facing skill definition
│   ├── references/
│   │   └── api-and-schema.md      # API contract, categories, field map, lark-cli notes
│   └── scripts/
│       ├── sync.py                # ← orchestrator / daily entry point
│       ├── pipeline.py            # list sweep, detail parsing, weekly-hot parsing
│       ├── categories.py          # 32-category reverse lookup
│       ├── load.py                # row building + Bitable batch writes
│       ├── setup_base.sh          # create the Bitable
│       ├── schedule.sh            # launchd management
│       └── fields.json            # Bitable schema (28 fields)
└── docs/
    ├── USAGE-and-prompts.md       # operations manual + ready-to-paste agent prompts (zh)
    └── BUILD-NOTES.md             # scraping notes, field provenance (zh)
```

Drop `skill/youmind-video-prompts-sync` into `~/.agents/skills/` and any agent that reads
skills will pick it up.

## Scheduling

macOS (installed by `schedule.sh`):

```bash
./schedule.sh install 09:30
./schedule.sh status
./schedule.sh logs
```

Linux — use cron instead:

```cron
30 9 * * * YOUMIND_DATA_DIR=$HOME/.youmind-sync /usr/bin/python3 $HOME/.agents/skills/youmind-video-prompts-sync/scripts/sync.py
```

## Configuration

Everything lives in `~/.youmind-sync/` (override with `YOUMIND_DATA_DIR`):

| File | Purpose |
|---|---|
| `config.json` | `base_token`, `table_id`, `identity` |
| `state.json` | synced ids, weekly-hot ids, last run result |
| `prompts_list.jsonl` | raw list-API metadata checkpoint |
| `prompts_full.jsonl` | detail-page stats + categories |
| `categories.json` | id → category tags |
| `sync.log` | run log |

Environment overrides: `YOUMIND_DATA_DIR`, `YOUMIND_BASE_TOKEN`, `YOUMIND_TABLE_ID`,
`YOUMIND_IDENTITY`, `SCRAPE_RATE`, `SCRAPE_WORKERS`, `DETAIL_TOP`.

**Idempotent.** If `state.json` is lost the sync reads the `提示词ID` values already in your
Bitable and treats them as known, so nothing is ever double-inserted.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `{"error":"Forbidden"}` from the API | missing `Origin` / `Referer` headers (the scripts set them) |
| Site-wide 429 with a large `retry-after` | Cloudflare rate limit. Wait it out (the script polls), then lower `SCRAPE_RATE` |
| `lark-cli ... 91403` | the bot cannot access that Bitable — add it as a collaborator, or retry once with `YOUMIND_IDENTITY=user` |
| Detail page 404 | the prompt was delisted; recorded as `_httpStatus` and skipped |
| A batch write fails | retried 5× per batch, then the run exits non-zero; re-running skips completed batches |

## Scope and legal notes

This repository contains **only code**. It does not ship any scraped prompts, author handles,
or video URLs — those belong to their original creators and to YouMind / X. You are
responsible for how you use the tool and for complying with the target site's terms of
service. Be polite: the defaults are deliberately slow.


## Development

```bash
./scripts/check.sh     # python + shell syntax, SKILL.md manifest, secret scan, rate guard
```

That is the same set of assertions the GitHub Actions workflow runs. CI needs the
`workflow` OAuth scope, which the default `gh` login does not request — a
`.github/workflows/ci.yml` is kept in the tree but untracked until you enable it:

```bash
gh auth refresh --hostname github.com -s workflow
git add .github && git commit -m "ci: add GitHub Actions check" && git push
```

## License

[MIT](LICENSE)
