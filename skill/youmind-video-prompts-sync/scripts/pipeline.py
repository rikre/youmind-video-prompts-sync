#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YouMind video-prompt library scraper.

Phase A  enumerate the full Seedance 2.0 / 2.5 libraries via the public
         /youmarketing-api/video-prompts endpoint (sorted by views desc, so the
         head of each list is the hot set)
Phase B  fetch detail pages for the top N of each model to collect
         浏览量 / 点赞 / 评论 / 分享 / 收藏 / 引用 plus 分类标签
Phase C  parse the 每周最热 block from the /prompts/video landing page

The site sits behind Cloudflare; bursting gets the whole zone 429'd for ~1h.
Everything is throttled by a shared adaptive rate limiter and checkpointed, so
re-running resumes instead of restarting.
"""
import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter

# data directory: override with YOUMIND_DATA_DIR so a scheduled run keeps its
# checkpoints outside the (possibly read-only) skill folder
OUT = os.environ.get("YOUMIND_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
LIST_FILE = os.path.join(OUT, "prompts_list.jsonl")
FULL_FILE = os.path.join(OUT, "prompts_full.jsonl")
PROGRESS = os.path.join(OUT, "progress.json")
WEEKLY_JSON = os.path.join(OUT, "weekly.json")

API = "https://youmind.com/youmarketing-api/video-prompts"
LANDING = "https://youmind.com/zh-CN/prompts/video"
HDRS = {
    "Content-Type": "application/json",
    "Origin": "https://youmind.com",
    "Referer": "https://youmind.com/zh-CN/seedance-2-0-prompts/explore",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}
MODELS = [
    ("seedance-2.0", "Seedance 2.0"),
    ("seedance-2.5", "Seedance 2.5"),
]
DETAIL_TOP = int(os.environ.get("DETAIL_TOP", "500"))
RATE = float(os.environ.get("SCRAPE_RATE", "1.5"))
WORKERS = int(os.environ.get("SCRAPE_WORKERS", "4"))

session = requests.Session()
session.headers.update(HDRS)
_ad = HTTPAdapter(pool_connections=32, pool_maxsize=32)
session.mount("https://", _ad)
session.mount("http://", _ad)

_rl = threading.Lock()
_next = [0.0]
_state = {"rate": RATE}


def log(*a):
    print(*a, flush=True)


def set_rate(rate):
    with _rl:
        _state["rate"] = float(rate)


def throttle():
    with _rl:
        now = time.time()
        if _next[0] > now:
            time.sleep(_next[0] - now)
            now = time.time()
        _next[0] = now + 1.0 / _state["rate"]


def on_429(where=""):
    """Adaptive back-off: shrink the global request rate whenever Cloudflare pushes back."""
    with _rl:
        old = _state["rate"]
        _state["rate"] = max(0.25, old * 0.6)
        new = _state["rate"]
        _next[0] = max(_next[0], time.time() + 45.0)
    if new != old:
        log("  429 at %s -> rate %.2f/s (was %.2f/s)" % (where, new, old))


def wait_until_unblocked(max_wait=7200):
    """Cloudflare 429s the whole zone; poll until it clears."""
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            r = session.get(LANDING, timeout=30)
            if r.status_code == 200:
                return True
            ra = r.headers.get("retry-after")
            log("blocked: HTTP %s retry-after=%s" % (r.status_code, ra))
            wait = min(int(ra) + 5 if (ra or "").isdigit() else 120, 900)
        except Exception as e:
            log("probe error", e)
            wait = 120
        time.sleep(max(30, wait))
    return False


def api_page(model, page, limit=50, tries=8, sort_by="views", order="desc"):
    """sort_by="views" ranks the curated hot set; sort_by="id" gives a stable newest-first feed."""
    body = {"page": page, "limit": limit, "locale": "zh-CN", "model": model,
            "sortBy": sort_by, "sortOrder": order, "reviewedOnly": False}
    for t in range(tries):
        throttle()
        try:
            r = session.post(API, json=body, timeout=45)
            if r.status_code == 200:
                return r.json()
            log("api http", r.status_code, model, page)
            if r.status_code == 429:
                on_429("list.%s.p%s" % (model, page))
                time.sleep(min(600, 20 * (2 ** t)) + random.random() * 3)
                continue
        except Exception as e:
            log("api err", e, model, page)
        time.sleep(3.0 * (t + 1))
    raise RuntimeError("api failed %s p%s" % (model, page))


def _read_jsonl(path):
    rows = {}
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            try:
                it = json.loads(l)
                rows[it["id"]] = it
            except Exception:
                pass
    return rows


def enumerate_all():
    """Full enumeration of both model libraries (resumable via per-model checkpoints)."""
    rows = _read_jsonl(LIST_FILE)
    if rows:
        log("reuse list", len(rows))
        return list(rows.values())
    for model, label in MODELS:
        ckpt = os.path.join(OUT, "list_%s.jsonl" % model)
        if os.path.exists(ckpt):
            got = _read_jsonl(ckpt)
            rows.update(got)
            log("resume", model, len(got))
            continue
        first = api_page(model, 1)
        total = first["total"]
        pages = (total + 49) // 50
        log("model", model, "total", total, "pages", pages)
        cf = open(ckpt, "w", encoding="utf-8")
        for p in range(1, pages + 1):
            d = api_page(model, p)
            plist = d.get("prompts", [])
            if not plist:
                break
            for i, it in enumerate(plist):
                it["_model"] = label
                it["_modelKey"] = model
                it["_rank"] = (p - 1) * 50 + i
                rows[it["id"]] = it
                cf.write(json.dumps(it, ensure_ascii=False) + "\n")
            if p % 10 == 0 or p == pages:
                cf.flush()
                log("  ", model, p, "/", pages, "acc", len(rows))
        cf.close()
    out = list(rows.values())
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log("enumerated", len(out))
    return out


def enumerate_incremental(known, max_pages=200):
    """Sweep the whole views-desc feed and return (all_items, new_items).

    There is no cheaper "newest first" feed to poll: the API silently ignores
    unknown sortBy values (id / createdAt / publishedAt all fall back to the same
    default editorial order), and a freshly published prompt has too few views to
    reach the head of the views ranking. So a full ~158-request sweep (~2 min at
    the default rate) is the reliable way to spot what is new. Sweeping by views
    also yields the Top-N ranking used by --refresh-top for free.
    """
    all_items, fresh = [], []
    for model, label in MODELS:
        first = api_page(model, 1)
        total = first.get("total") or 0
        pages = min(max_pages, (total + 49) // 50) if total else max_pages
        for p in range(1, pages + 1):
            d = first if p == 1 else api_page(model, p)
            plist = d.get("prompts", [])
            if not plist:
                break
            for i, it in enumerate(plist):
                it["_model"] = label
                it["_modelKey"] = model
                it["_rank"] = (p - 1) * 50 + i
            all_items.extend(plist)
            fresh.extend([it for it in plist if it["id"] not in known])
            if p % 20 == 0 or p == pages:
                log("  %s %d/%d (new so far %d)" % (model, p, pages, len(fresh)))
    return all_items, fresh


def enumerate_since(since_iso, max_pages=60):
    """Date-window sweep using `sortBy=publishedAt` — cheap incremental discovery.

    `publishedAt` DOES work, unlike `id`/`createdAt`: from the 7th item of page 1
    onward the feed is strictly date-descending. The first few items on page 1 are
    a pinned `featured` block carrying old dates, so the stop rule cannot be
    "the page's oldest item is older than `since`" — it has to be "no item on this
    page is newer than `since`". A quiet day costs one or two requests.

    Returns every prompt found in the window (not just unseen ones); the caller
    still de-duplicates against the ids already in the Bitable.
    """
    found = []
    for model, label in MODELS:
        for p in range(1, max_pages + 1):
            d = api_page(model, p, sort_by="publishedAt")
            plist = d.get("prompts", [])
            if not plist:
                break
            for i, it in enumerate(plist):
                it["_model"] = label
                it["_modelKey"] = model
                it["_rank"] = (p - 1) * 50 + i
            found.extend(plist)
            if not any((it.get("sourcePublishedAt") or "") >= since_iso for it in plist):
                log("  %s: page %d has nothing newer than %s, stop"
                    % (model, p, since_iso[:10]))
                break
    return found


STAT_RE = re.compile(
    r'>(点赞|浏览|分享|评论|收藏|引用)</span></div><div class="[^"]*">([^<]*)</div>')
CAT_RE = re.compile(r'href="[^"]*\?categories=([a-z0-9\-]+)"[^>]*>([^<]+)</a>')


def num(v):
    if v is None:
        return None
    v = str(v).replace(",", "").strip()
    mult = 1
    if v[-1:] in ("K", "k"):
        mult, v = 1000, v[:-1]
    elif v[-1:] in ("M", "m"):
        mult, v = 1000000, v[:-1]
    try:
        return int(float(v) * mult)
    except Exception:
        return None


def parse_detail(html, item):
    rec = {k: item.get(k) for k in ("id", "slug", "title", "_model", "_modelKey", "_rank")}
    stats = dict(STAT_RE.findall(html))
    cats = []
    for slug, name in CAT_RE.findall(html):
        if name not in cats:
            cats.append(name)
    ld, video = None, None
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        for node in d.get("@graph", []):
            if node.get("@type") == "CreativeWork":
                ld = node
            elif node.get("@type") == "VideoObject":
                video = node
    if ld:
        tmap = {"LikeAction": "_likes", "ViewAction": "_views",
                "CommentAction": "_comments", "ShareAction": "_shares"}
        for s in ld.get("interactionStatistic") or []:
            k = tmap.get((s.get("interactionType") or {}).get("@type"))
            if k:
                rec[k] = s.get("userInteractionCount")
        if ld.get("inLanguage"):
            rec["_ldLang"] = ld["inLanguage"]
        if ld.get("datePublished"):
            rec["_ldDate"] = ld["datePublished"]
        if not rec.get("title") and ld.get("name"):
            rec["title"] = ld["name"]
        rec["_ldTitle"] = ld.get("name")
        rec["_ldDesc"] = ld.get("description")
        rec["_ldPrompt"] = ld.get("text")
        rec["_ldAuthor"] = ld.get("author")
        rec["_ldSource"] = ld.get("isBasedOn")
        rec["_ldImage"] = ld.get("image")
        rec["_ldModel"] = (ld.get("about") or {}).get("name")
    if video:
        rec["_ldVideo"] = video.get("contentUrl")
        rec["_ldVideoName"] = video.get("name")
    rec["_cats"] = cats
    rec["_bookmarks"] = num(stats.get("收藏"))
    rec["_quotes"] = num(stats.get("引用"))
    if rec.get("_likes") is None:
        rec["_likes"] = num(stats.get("点赞"))
    if rec.get("_comments") is None:
        rec["_comments"] = num(stats.get("评论"))
    if rec.get("_shares") is None:
        rec["_shares"] = num(stats.get("分享"))
    if rec.get("_views") is None:
        rec["_views"] = num(stats.get("浏览"))
    return rec


def detail_url(it):
    slug = it.get("slug") or ""
    return "https://youmind.com/zh-CN/video-prompts/" + (
        "%s-%s" % (slug, it["id"]) if slug else str(it["id"]))


def fetch_one(it, tries=6):
    url = detail_url(it)
    for t in range(tries):
        throttle()
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 200:
                return parse_detail(r.text, it)
            if r.status_code in (404, 410):
                return {"id": it["id"], "_httpStatus": r.status_code, "_slug": it.get("slug")}
            if r.status_code == 429:
                on_429("detail.%s" % it["id"])
                time.sleep(min(600, 20 * (2 ** t)) + random.random() * 3)
                continue
        except Exception:
            pass
        time.sleep(2.0 * (t + 1))
    return {"id": it["id"], "_error": "fetch failed", "_slug": it.get("slug")}


def parse_weekly():
    """Parse the 每周最热 gallery on the landing page."""
    ff = os.path.join(OUT, "weekly.html")
    r = session.get(LANDING, timeout=45)
    if r.status_code != 200:
        log("weekly landing http", r.status_code)
        if not os.path.exists(ff):
            return []
    else:
        open(ff, "w", encoding="utf-8").write(r.text)
    h = open(ff, encoding="utf-8", errors="replace").read()
    i = h.find('id="prompts-weekly-highlights"')
    if i < 0:
        return []
    seg = h[i:]
    j = seg.find('id="prompts-models"')
    if j > 0:
        seg = seg[:j]
    items, seen = [], set()
    for m in re.finditer(r'href="(/zh-CN/video-prompts/([a-z0-9\-]+)-(\d+))"(.*?)</a>', seg, re.S):
        href, slug, pid, body = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if pid in seen:
            continue
        seen.add(pid)
        t = re.search(r'<h3[^>]*>(.*?)</h3>', body, re.S)
        img = re.search(r'src="([^"]+)"', body)
        spans = re.findall(r'<span class="truncate">(.*?)</span>', body, re.S)
        items.append({
            "id": pid, "slug": slug,
            "title": t.group(1).strip() if t else "",
            "author": {"name": (spans[0].lstrip("@") if spans else "")},
            "cover": img.group(1) if img else "",
            "_model": spans[-1] if len(spans) > 1 else "",
            "_modelKey": "", "_weekly": True,
            "_url": "https://youmind.com" + href,
        })
    json.dump(items, open(WEEKLY_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log("weekly items", len(items))
    return items


def tops(items, n=DETAIL_TOP):
    """The n most-viewed prompts of each model (head of the views-desc feed)."""
    picked = []
    for model, _ in MODELS:
        cand = [it for it in items if it.get("_modelKey") == model]
        cand.sort(key=lambda x: x.get("_rank", 10 ** 9))
        picked.extend(cand[:n])
    return picked


def fetch_details(targets, append=True):
    """Fetch + parse detail pages concurrently; append results to prompts_full.jsonl."""
    have = _read_jsonl(FULL_FILE)
    todo = [it for it in targets if it["id"] not in have]
    log("detail targets", len(targets), "todo", len(todo))
    if not todo:
        return have
    f = open(FULL_FILE, "a", encoding="utf-8")
    lock = threading.Lock()
    done, t0 = 0, time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, it): it for it in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"id": futs[fut]["id"], "_error": str(e)}
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done += 1
                if done % 50 == 0:
                    f.flush()
                    el = time.time() - t0
                    rate = done / el if el else 0
                    log("  %d/%d %.2f/s" % (done, len(todo), rate))
                    json.dump({"done": done, "total": len(todo)}, open(PROGRESS, "w"))
    f.close()
    return _read_jsonl(FULL_FILE)


def main():
    """Standalone full refresh: enumerate everything, refresh top-N stats, parse weekly."""
    if not wait_until_unblocked():
        log("still blocked after max wait")
        return 1
    items = enumerate_all()
    weekly = parse_weekly()
    targets = tops(items) + weekly
    have = fetch_details(targets)
    wids = {w["id"] for w in weekly}
    if wids:
        with open(FULL_FILE, "w", encoding="utf-8") as f:
            for r in have.values():
                if r["id"] in wids:
                    r["_weekly"] = True
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log("DONE details", len(have))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
