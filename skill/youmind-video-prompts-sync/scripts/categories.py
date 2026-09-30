#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map every prompt id -> its 32 YouMind video categories.

The list API does not return categories; only detail pages do. But the list API
accepts `videoCategoryFilters` ({useCases|styles|subjects: [id]}), so querying
each of the 32 categories once yields the complete mapping without touching
7,874 detail pages (~10 min at 1.5 req/s vs. ~90 min).

Writes categories.json into YOUMIND_DATA_DIR.
"""
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

OUT = os.environ.get("YOUMIND_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
OUTFILE = os.path.join(OUT, "categories.json")
API = "https://youmind.com/youmarketing-api/video-prompts"
HDRS = {
    "Content-Type": "application/json",
    "Origin": "https://youmind.com",
    "Referer": "https://youmind.com/zh-CN/seedance-2-0-prompts/explore",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}
MODELS = ["seedance-2.0", "seedance-2.5"]

CATS = [
    ("useCases", 87, "电影级场景展示"), ("useCases", 88, "Vlog / 生活记录"),
    ("useCases", 89, "短片"), ("useCases", 90, "音乐视频"),
    ("useCases", 91, "品牌 / 产品广告"), ("useCases", 92, "UGC / 口播广告"),
    ("useCases", 93, "讲解 / 教程"), ("useCases", 94, "频道片头 / 品牌素材"),
    ("useCases", 95, "游戏宣传片 / PV"),
    ("styles", 96, "电影级写实风格"), ("styles", 97, "奇幻 / 魔法"),
    ("styles", 98, "赛博朋克 / 科幻"), ("styles", 99, "动漫"),
    ("styles", 100, "复古 / 怀旧胶片"), ("styles", 101, "超现实 / 梦境"),
    ("styles", 102, "纪录片"), ("styles", 103, "3D 卡通"),
    ("styles", 104, "2D 动画"), ("styles", 105, "中国水墨"),
    ("styles", 106, "定格动画"),
    ("subjects", 107, "人物 / 角色"), ("subjects", 108, "运动 / 动作"),
    ("subjects", 109, "自然 / 风景"), ("subjects", 110, "建筑 / 室内"),
    ("subjects", 111, "抽象 / VFX"), ("subjects", 112, "城市 / 街景"),
    ("subjects", 113, "动物 / 宠物"), ("subjects", 114, "交通工具"),
    ("subjects", 115, "文字 / Logo"), ("subjects", 116, "人群 / 群体"),
    ("subjects", 117, "美食 / 饮品"), ("subjects", 118, "产品"),
]

RATE = float(os.environ.get("SCRAPE_RATE", "1.5"))
_state = {"rate": RATE}
_rl = threading.Lock()
_next = [0.0]

session = requests.Session()
session.headers.update(HDRS)
session.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))


def log(*a):
    print(*a, flush=True)


def throttle():
    with _rl:
        now = time.time()
        if _next[0] > now:
            time.sleep(_next[0] - now)
            now = time.time()
        _next[0] = now + 1.0 / _state["rate"]


def on_429():
    with _rl:
        _state["rate"] = max(0.25, _state["rate"] * 0.6)
        _next[0] = max(_next[0], time.time() + 45)


def api(model, dim, cid, page, limit=50, tries=8):
    body = {"page": page, "limit": limit, "locale": "zh-CN", "model": model,
            "videoCategoryFilters": {dim: [cid]}}
    for t in range(tries):
        throttle()
        try:
            r = session.post(API, json=body, timeout=45)
            if r.status_code == 200:
                return r.json()
            log("http", r.status_code, model, dim, cid, page)
            if r.status_code == 429:
                on_429()
                time.sleep(min(600, 20 * (2 ** t)) + random.random() * 3)
                continue
        except Exception as e:
            log("err", e)
        time.sleep(3 * (t + 1))
    raise RuntimeError("failed %s %s %s p%s" % (model, dim, cid, page))


def one(job):
    model, dim, cid, name = job
    ids, page, total = [], 1, None
    while True:
        d = api(model, dim, cid, page)
        pl = d.get("prompts", [])
        total = d.get("total", total)
        if not pl:
            break
        ids.extend(it["id"] for it in pl)
        if not d.get("hasMore") or page > 400:
            break
        page += 1
    return name, ids, total


def main():
    mapping = {}
    if os.path.exists(OUTFILE):
        try:
            mapping = json.load(open(OUTFILE, encoding="utf-8"))
        except Exception:
            mapping = {}
    jobs = [(m, dim, cid, name) for m in MODELS for (dim, cid, name) in CATS]
    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        for name, ids, total in ex.map(one, jobs):
            with lock:
                for pid in ids:
                    mapping.setdefault(str(pid), [])
                    if name not in mapping[str(pid)]:
                        mapping[str(pid)].append(name)
                done += 1
                log("[%d/%d] %s -> %d ids (total %s), mapped %d prompts"
                    % (done, len(jobs), name, len(ids), total, len(mapping)))
                tmp = OUTFILE + ".tmp"
                json.dump(mapping, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(tmp, OUTFILE)
    log("categories.json written:", len(mapping), "prompts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
