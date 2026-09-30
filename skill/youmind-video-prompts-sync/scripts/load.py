#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Feishu Bitable rows from the scraped JSONL and push them via lark-cli.

    python3 load.py                       # build rows + report
    python3 load.py push                  # push every row (resumable via pushed.txt)
    python3 load.py push <offset> <limit> # bounded push (smoke test)

Data dir comes from YOUMIND_DATA_DIR (defaults to this folder).
Base / table come from YOUMIND_BASE_TOKEN / YOUMIND_TABLE_ID, or config.json in
the data dir, or the built-in defaults below.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("YOUMIND_DATA_DIR") or HERE
BATCH = 100
MAX_TEXT = 60000
IDENTITY = os.environ.get("YOUMIND_IDENTITY", "bot")

# lark-cli profile (multi-tenant): when set, every lark-cli call gets --profile <p>
PROFILE = os.environ.get("YOUMIND_PROFILE", "")

MODEL_MAP = {
    "seedance-2.0": "Seedance 2.0",
    "seedance-2.5": "Seedance 2.5",
    "grok-imagine": "Grok Imagine",
}


def _config():
    cfg = {}
    for p in (os.path.join(OUT, "config.json"), os.path.join(HERE, "config.json")):
        if os.path.exists(p):
            try:
                cfg.update(json.load(open(p, encoding="utf-8")))
            except Exception:
                pass
    return cfg


def profile_args():
    """`--profile X` for every lark-cli call, or [] when running on the default app."""
    p = PROFILE or _config().get("profile") or ""
    return ["--profile", str(p)] if p else []


def base_token():
    v = os.environ.get("YOUMIND_BASE_TOKEN") or _config().get("base_token")
    if not v:
        raise SystemExit("缺少 base_token：先跑 scripts/setup_base.sh，"
                         "或设置 YOUMIND_BASE_TOKEN / config.json")
    return v


def table_id():
    v = os.environ.get("YOUMIND_TABLE_ID") or _config().get("table_id")
    if not v:
        raise SystemExit("缺少 table_id：先跑 scripts/setup_base.sh，"
                         "或设置 YOUMIND_TABLE_ID / config.json")
    return v


def load_jsonl(path):
    """Read a JSONL file, transparently falling back to <path>.gz."""
    d = {}

    def eat(lines):
        for l in lines:
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            if r.get("id") is not None:
                d[r["id"]] = r

    if os.path.exists(path):
        eat(open(path, encoding="utf-8"))
    elif os.path.exists(path + ".gz"):
        import gzip
        eat(gzip.open(path + ".gz", "rt", encoding="utf-8"))
    return d


def norm_lang(x):
    x = (x or "").lower()
    for p, v in (("zh", "zh"), ("en", "en"), ("ja", "ja"), ("ko", "ko")):
        if x.startswith(p):
            return v
    return "other" if x else None


def to_local(dt):
    """ISO8601 UTC -> 'YYYY-MM-DD HH:mm:ss' at UTC+8 (base timezone is +08:00)."""
    if not dt:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", str(dt))
    if not m:
        return None
    try:
        d = datetime.datetime(*[int(v) for v in m.groups()]) + datetime.timedelta(hours=8)
    except Exception:
        return None
    return d.strftime("%Y-%m-%d %H:%M:%S")


def clip(s, n=MAX_TEXT):
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[:n]


def build_rows(only_ids=None, sort_by_views=True):
    lst = load_jsonl(os.path.join(OUT, "prompts_list.jsonl"))
    full = load_jsonl(os.path.join(OUT, "prompts_full.jsonl"))
    catmap = {}
    cp = os.path.join(OUT, "categories.json")
    if os.path.exists(cp):
        catmap = json.load(open(cp, encoding="utf-8"))
    weekly = {}
    wp = os.path.join(OUT, "weekly.json")
    if os.path.exists(wp):
        for it in json.load(open(wp, encoding="utf-8")):
            weekly[it["id"]] = it

    ids = set(lst) | set(full) | set(weekly)
    if only_ids is not None:
        ids = {i for i in ids if i in only_ids}
    rows, truncated = [], 0
    for pid in ids:
        a = lst.get(pid, {})
        b = full.get(pid, {})
        w = weekly.get(pid, {})
        title = a.get("title") or w.get("title") or b.get("_ldTitle") or ""
        if not title:
            continue
        slug = a.get("slug") or w.get("slug") or b.get("slug") or ""
        videos = a.get("videos") or []
        v0 = videos[0] if videos else {}
        author = a.get("author") or b.get("_ldAuthor") or w.get("author") or {}
        model = (a.get("_model") or b.get("_model") or w.get("_model")
                 or MODEL_MAP.get(a.get("_modelKey", "")) or b.get("_ldModel") or "")
        lang = norm_lang(a.get("language") or b.get("_ldLang"))
        content = a.get("content") or b.get("_ldPrompt") or ""
        translated = a.get("translatedContent") or ""
        if lang == "zh":
            translated = ""
        if len(content) > MAX_TEXT or len(translated) > MAX_TEXT:
            truncated += 1
        cats = [c for c in (b.get("_cats") or []) if c]
        for c in catmap.get(str(pid), []):
            if c not in cats:
                cats.append(c)
        row = {
            "标题": clip(title, 900),
            "提示词ID": pid,
            "Slug": slug,
            "来源板块": ("Seedance 2.0 库" if model == "Seedance 2.0"
                     else "Seedance 2.5 库" if model == "Seedance 2.5"
                     else "每周最热"),
            "每周最热": bool(b.get("_weekly") or w),
            "模型类型": model or None,
            "作者": author.get("name") or None,
            "作者主页": author.get("link") or None,
            "封面图": v0.get("thumbnail") or w.get("cover") or b.get("_ldImage") or None,
            "视频链接": v0.get("sourceUrl") or b.get("_ldVideo") or None,
            "视频标题": v0.get("caption") or b.get("_ldVideoName") or None,
            "详情页链接": ("https://youmind.com/zh-CN/video-prompts/%s" % (
                ("%s-%s" % (slug, pid)) if slug else pid)),
            "原始来源推文": a.get("sourceLink") or b.get("_ldSource") or None,
            "提示词简介": clip(a.get("description") or b.get("_ldDesc"), 4000),
            "原始提示词": clip(content),
            "中文译文": clip(translated),
            "原始语言": lang,
            "分类标签": cats or None,
            "发布时间": to_local(a.get("sourcePublishedAt") or b.get("_ldDate")),
            "浏览量": b.get("_views"),
            "点赞量": b.get("_likes"),
            "评论量": b.get("_comments"),
            "分享量": b.get("_shares"),
            "收藏量": b.get("_bookmarks"),
            "引用量": b.get("_quotes"),
            "素材类型": "视频" if (v0.get("sourceUrl") or b.get("_ldVideo")) else (
                "图片" if (v0.get("thumbnail") or b.get("_ldImage")) else "无素材"),
            "是否精选": bool(a.get("featured")),
        }
        row = {k: v for k, v in row.items() if v is not None and v != ""}
        rows.append((b.get("_views") or 0, row))

    if sort_by_views:
        rows.sort(key=lambda x: -x[0])
    if only_ids is None:
        print("built %d rows (%d with text truncated at %d chars)"
              % (len(rows), truncated, MAX_TEXT))
        print("rows carrying interaction stats:",
              sum(1 for _, r in rows if "浏览量" in r))
        print("weekly-flagged rows:", sum(1 for _, r in rows if r.get("每周最热")))
    return [r for _, r in rows]


def push(rows, start=0, limit=None, done_file=None, identity=None, quiet=False):
    """Batch-create rows; every completed offset is journalled so re-runs resume."""
    if not rows:
        return 0
    identity = identity or IDENTITY
    done_file = done_file or os.path.join(OUT, "pushed.txt")
    pushed = set()
    if os.path.exists(done_file):
        pushed = set(int(x) for x in open(done_file).read().split() if x.strip())
    end = len(rows) if limit is None else min(len(rows), start + limit)
    # lark-cli only accepts @file payloads from the CWD, /tmp or ~/files, and the
    # data dir is usually none of those — so stage the batch under /tmp.
    # (tempfile.gettempdir() is /var/folders/... on macOS and would be rejected.)
    payload_path = "/tmp/youmind-payload-%d.json" % os.getpid()
    sent = 0
    for i in range(start, end, BATCH):
        if i in pushed:
            continue
        chunk = rows[i:i + BATCH]
        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump({"create_records": chunk}, f, ensure_ascii=False)
        ok = False
        for attempt in range(5):
            r = subprocess.run(
                ["lark-cli", *profile_args(), "base", "+record-batch-create",
                 "--base-token", base_token(), "--table-id", table_id(),
                 "--json", "@" + payload_path, "--as", identity, "--jq", ".ok"],
                capture_output=True, text=True)
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            if out == "true":
                open(done_file, "a").write("%d\n" % i)
                sent += len(chunk)
                if not quiet:
                    print("batch %d-%d ok" % (i, i + len(chunk)), flush=True)
                ok = True
                break
            print("batch %d attempt %d failed: %s" % (i, attempt, out[:500]), flush=True)
            time.sleep(2 * (attempt + 1))
        if not ok:
            raise RuntimeError("batch %d failed after retries" % i)
        time.sleep(0.4)
    try:
        os.remove(payload_path)
    except OSError:
        pass
    return sent


def _as_int(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def known_ids_from_base(identity=None, progress=False):
    """Read every 提示词ID already in the Base (offset pagination, projected field).

    Handles both response shapes lark-cli can return: the column matrix
    (`data.data` + `data.fields`) and a list of `{fields: {...}}` items.
    """
    identity = identity or IDENTITY
    ids, offset, page = set(), 0, 200
    while True:
        r = subprocess.run(
            ["lark-cli", *profile_args(), "base", "+record-list",
             "--base-token", base_token(), "--table-id", table_id(),
             "--field-id", "提示词ID", "--limit", str(page),
             "--offset", str(offset), "--as", identity, "--format", "json"],
            capture_output=True, text=True)
        txt = r.stdout or ""
        try:
            data = json.loads(txt[txt.index("{"):])
        except Exception:
            break
        d = data.get("data") or {}
        got, n = 0, 0
        rows = d.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], list):
            fields = d.get("fields") or []
            idx = fields.index("提示词ID") if "提示词ID" in fields else 0
            for row in rows:
                n += 1
                v = _as_int(row[idx]) if idx < len(row) else None
                if v is not None:
                    ids.add(v)
                    got += 1
        else:
            items = d.get("items") or []
            for it in items:
                n += 1
                v = _as_int((it.get("fields") or {}).get("提示词ID"))
                if v is not None:
                    ids.add(v)
                    got += 1
        if progress:
            print("  offset %d: +%d (total %d)" % (offset, got, len(ids)), flush=True)
        if n < page or not d.get("has_more", n >= page):
            break
        offset += page
    return ids


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "known":
        ids = known_ids_from_base(progress=True)
        print("known ids in base:", len(ids))
        sys.exit(0)
    rows = build_rows()
    json.dump(rows, open(os.path.join(OUT, "records.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("records.json written")
    if len(sys.argv) > 1 and sys.argv[1] == "push":
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
        push(rows, start, limit)
