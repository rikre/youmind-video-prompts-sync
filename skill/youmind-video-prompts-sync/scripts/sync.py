#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Incremental YouMind 视频提示词 -> 飞书多维表格 sync.

Designed to be run unattended (launchd / cron / manual):

    python3 sync.py                  # 增量：只抓新增提示词并写入
    python3 sync.py --refresh-top    # 额外刷新各模型 Top N 的互动数据
    python3 sync.py --full           # 全量重建（首次建表后补齐用）
    python3 sync.py --backfill-categories
    python3 sync.py --dry-run        # 只报告，不写飞书
    python3 sync.py --status         # 打印上次运行结果与状态

Exit code 0 = success, 1 = failure (so the scheduler can alert).

State lives in ~/.youmind-sync (override with YOUMIND_DATA_DIR):
    state.json          synced prompt ids / weekly ids / last run info
    prompts_list.jsonl  full list-API metadata checkpoint
    prompts_full.jsonl  detail-page interaction stats
    categories.json     id -> 分类标签 map
    weekly.json         this run's 每周最热
    sync.log            run log
"""
import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_STATE_DIR = os.path.expanduser("~/.youmind-sync")
DATA_DIR = os.path.expanduser(os.environ.get("YOUMIND_DATA_DIR") or DEFAULT_STATE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
os.environ["YOUMIND_DATA_DIR"] = DATA_DIR

import pipeline          # noqa: E402
import load as loader    # noqa: E402
try:
    import categories as catmod   # noqa: E402
except Exception:                 # pragma: no cover - optional backfill helper
    catmod = None

STATE = os.path.join(DATA_DIR, "state.json")
LOG = os.path.join(DATA_DIR, "sync.log")

DEFAULT_CONFIG = {
    # no defaults on purpose: fill these in ~/.youmind-sync/config.json
    # (setup_base.sh writes that file for you)
    "base_token": "",
    "table_id": "",
    "identity": "bot",
    "rate": 1.5,
    "workers": 4,
    "detail_top": 500,
}


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(*a):
    line = "[%s] %s" % (now(), " ".join(str(x) for x in a))
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(DATA_DIR, "config.json")
    if os.path.exists(p):
        try:
            cfg.update(json.load(open(p, encoding="utf-8")))
        except Exception:
            log("WARN config.json unreadable, using defaults")
    for k, env in (("base_token", "YOUMIND_BASE_TOKEN"),
                   ("table_id", "YOUMIND_TABLE_ID"),
                   ("identity", "YOUMIND_IDENTITY"),
                   ("rate", "SCRAPE_RATE"),
                   ("workers", "SCRAPE_WORKERS"),
                   ("detail_top", "DETAIL_TOP")):
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    cfg["rate"] = float(cfg["rate"])
    cfg["workers"] = int(cfg["workers"])
    cfg["detail_top"] = int(cfg["detail_top"])
    return cfg


def read_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            log("WARN state.json corrupt, rebuilding from the Base")
    return {}


def write_state(st):
    st["updated_at"] = now()
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def materialize_gz(path):
    """If only <path>.gz exists, expand it so later appends keep one source of truth."""
    if os.path.exists(path) or not os.path.exists(path + ".gz"):
        return
    import gzip
    import shutil
    with gzip.open(path + ".gz", "rt", encoding="utf-8") as src, \
            open(path, "w", encoding="utf-8") as dst:
        shutil.copyfileobj(src, dst)
    log("expanded", os.path.basename(path + ".gz"), "->", os.path.basename(path))


def run_journal(new_ids):
    """A push journal keyed by the exact new-id set, so a retried run never double-posts."""
    import hashlib
    key = hashlib.md5(",".join(str(i) for i in sorted(new_ids)).encode()).hexdigest()[:12]
    return os.path.join(DATA_DIR, "pushed_%s.txt" % key)


def append_list_jsonl(items):
    """Append new list items to prompts_list.jsonl without duplicating ids."""
    path = os.path.join(DATA_DIR, "prompts_list.jsonl")
    if not items:
        return
    have = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for l in f:
                try:
                    have.add(json.loads(l)["id"])
                except Exception:
                    pass
    with open(path, "a", encoding="utf-8") as f:
        for it in items:
            if it["id"] not in have:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
                have.add(it["id"])


def set_weekly_flags(set_true, set_false=()):
    """Flip the 每周最热 checkbox on already-synced rows (weekly hot rotates)."""
    import subprocess

    def record_id_for(pid):
        r = subprocess.run(
            ["lark-cli", "base", "+record-list",
             "--base-token", loader.base_token(), "--table-id", loader.table_id(),
             "--filter-json",
             json.dumps({"logic": "and", "conditions": [["提示词ID", "==", pid]]}),
             "--limit", "5", "--as", loader.IDENTITY, "--format", "json"],
            capture_output=True, text=True)
        try:
            d = json.loads((r.stdout or "")[r.stdout.index("{"):])["data"]
            return (d.get("record_id_list") or [None])[0]
        except Exception:
            return None

    changed = 0
    for pid, val in [(p, True) for p in set_true] + [(p, False) for p in set_false]:
        rid = record_id_for(pid)
        if not rid:
            continue
        r = subprocess.run(
            ["lark-cli", "base", "+record-batch-update",
             "--base-token", loader.base_token(), "--table-id", loader.table_id(),
             "--json", json.dumps({"record_id_list": [rid],
                                   "patch": {"每周最热": val}}, ensure_ascii=False),
             "--as", loader.IDENTITY, "--jq", ".ok"],
            capture_output=True, text=True)
        if (r.stdout or "").strip() == "true":
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser(description="YouMind 视频提示词 -> 飞书多维表格 增量同步")
    ap.add_argument("--full", action="store_true", help="全量枚举并补齐 Base 中缺失的记录")
    ap.add_argument("--refresh-top", action="store_true", help="刷新各模型 Top N 的互动数据")
    ap.add_argument("--backfill-categories", action="store_true", help="重跑全量分类映射")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写入飞书")
    ap.add_argument("--status", action="store_true", help="打印状态后退出")
    ap.add_argument("--max-pages", type=int, default=240, help="增量枚举最多翻多少页")
    args = ap.parse_args()

    cfg = config()
    if not cfg["base_token"] or not cfg["table_id"]:
        log("FAIL 未配置多维表格。先跑 scripts/setup_base.sh 建表，"
            "或在 ${DATA_DIR}/config.json 里填 base_token / table_id，"
            "或用 YOUMIND_BASE_TOKEN / YOUMIND_TABLE_ID 传入。")
        return 1
    os.environ.setdefault("YOUMIND_BASE_TOKEN", str(cfg["base_token"]))
    os.environ.setdefault("YOUMIND_TABLE_ID", str(cfg["table_id"]))
    loader.IDENTITY = str(cfg["identity"])
    pipeline.set_rate(cfg["rate"])
    pipeline.RATE = cfg["rate"]
    pipeline.WORKERS = cfg["workers"]
    pipeline.DETAIL_TOP = cfg["detail_top"]

    st = read_state()
    if args.status:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    t0 = time.time()
    log("=== sync start (data dir %s, base %s)" % (DATA_DIR, cfg["base_token"]))

    if not pipeline.wait_until_unblocked():
        log("FAIL still rate-limited after max wait")
        return 1

    synced = set(int(x) for x in st.get("synced_ids", []))
    if not synced:
        log("no local state -> reading existing 提示词ID from the Base")
        synced = loader.known_ids_from_base(progress=True)
        log("base already holds %d records" % len(synced))
    known = set(synced)

    # ---- 0. make sure checkpoints are editable plain jsonl -----------------------
    for name in ("prompts_list.jsonl", "prompts_full.jsonl"):
        materialize_gz(os.path.join(DATA_DIR, name))

    # ---- 1. discover new prompts -------------------------------------------------
    if args.full or len(known) < 100:
        items = pipeline.enumerate_all()
        new_items = [it for it in items if it["id"] not in known]
    else:
        items, new_items = pipeline.enumerate_incremental(known, max_pages=args.max_pages)
        log("sweep found %d prompts, %d of them new" % (len(items), len(new_items)))
    if new_items:
        append_list_jsonl(new_items)

    weekly = pipeline.parse_weekly()
    weekly_ids = {w["id"] for w in weekly}
    new_weekly = [w for w in weekly if w["id"] not in known]
    log("new prompts: %d, new weekly: %d" % (len(new_items), len(new_weekly)))

    # ---- 2. detail pages ---------------------------------------------------------
    targets = list(new_items) + list(new_weekly)
    if args.refresh_top:
        # `items` is already the views-desc sweep, so the head of each model IS the Top-N
        pool = items or list(loader.load_jsonl(
            os.path.join(DATA_DIR, "prompts_list.jsonl")).values())
        targets += pipeline.tops(pool, cfg["detail_top"])
    if args.backfill_categories and catmod:
        log("backfilling categories (this queries all 32 categories)")
        catmod.main()
    if targets and not args.dry_run:
        pipeline.fetch_details(targets)

    # ---- 3. push new rows --------------------------------------------------------
    new_ids = {it["id"] for it in new_items} | {w["id"] for w in new_weekly}
    # never re-flag rows that only refreshed their stats
    if args.refresh_top:
        new_ids -= {t["id"] for t in targets if t["id"] in known}
    pushed, rows = 0, []
    if new_ids:
        rows = loader.build_rows(only_ids=new_ids)
        log("rows to push: %d" % len(rows))
        if args.dry_run:
            log("dry-run: not writing to the Base")
        else:
            pushed = loader.push(rows, quiet=False, done_file=run_journal(new_ids))
            log("pushed %d records" % pushed)
    else:
        log("nothing new to push")

    # ---- 4. weekly flag rotation -------------------------------------------------
    if not args.dry_run and weekly_ids:
        prev = set(int(x) for x in st.get("weekly_ids", []))
        to_true = weekly_ids - prev
        to_false = prev - weekly_ids
        if to_true or to_false:
            n = set_weekly_flags(to_true, to_false)
            log("weekly flag updated on %d rows (+%d/-%d)"
                % (n, len(to_true), len(to_false)))

    if not args.dry_run:
        st["synced_ids"] = sorted(known | new_ids)
        st["weekly_ids"] = sorted(weekly_ids)
        st["last_run"] = now()
        st["last_run_ok"] = True
        st["last_new"] = len(new_ids)
        st["last_pushed"] = pushed
        st["total_synced"] = len(st["synced_ids"])
        st["elapsed_sec"] = round(time.time() - t0, 1)
        write_state(st)

    log("=== sync done in %.1fs (new %d, pushed %d, total %d)"
        % (time.time() - t0, len(new_ids), pushed,
           len(known | new_ids)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        log("FAIL %s: %s" % (type(e).__name__, e))
        st = read_state()
        st["last_run"] = now()
        st["last_run_ok"] = False
        st["last_error"] = "%s: %s" % (type(e).__name__, e)
        write_state(st)
        sys.exit(1)
