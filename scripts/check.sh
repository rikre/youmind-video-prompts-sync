#!/bin/bash
# Local sanity checks — the same ones CI runs.
#
#   ./scripts/check.sh
#
# Safe to run any time; touches nothing outside this repo.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

echo "==> python syntax"
for f in skill/youmind-video-prompts-sync/scripts/*.py; do
  if python3 -m py_compile "$f" 2>/dev/null; then ok "$f"; else bad "$f"; fi
done
find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "==> shell syntax"
for f in install.sh skill/youmind-video-prompts-sync/scripts/*.sh scripts/*.sh; do
  [ -f "$f" ] || continue
  if bash -n "$f" 2>/dev/null; then ok "$f"; else bad "$f"; fi
done

echo "==> skill manifest"
python3 - <<'PY' || fail=1
import pathlib, re, sys
p = pathlib.Path("skill/youmind-video-prompts-sync/SKILL.md")
text = p.read_text(encoding="utf-8")
if not text.startswith("---"):
    sys.exit("SKILL.md is missing YAML frontmatter")
fm = text.split("---", 2)[1]
missing = [k for k in ("name", "description") if not re.search(rf"^{k}\s*:\s*\S", fm, re.M)]
if missing:
    sys.exit("SKILL.md frontmatter missing: " + ", ".join(missing))
print("  ok   SKILL.md frontmatter")
PY

echo "==> secret scan"
if grep -rInE '(ou_[0-9a-f]{20,}|cli_[0-9a-f]{16,}|gho_[A-Za-z0-9]{20,}|tbl[A-Za-z0-9]{13})' \
     --include='*.py' --include='*.sh' --include='*.md' --include='*.json' . 2>/dev/null; then
  bad "possible credential or tenant token committed"
else
  ok "no obvious secrets"
fi

echo "==> upstream politeness"
python3 - <<'PY' || fail=1
import pathlib, re, sys
src = pathlib.Path("skill/youmind-video-prompts-sync/scripts/pipeline.py").read_text(encoding="utf-8")
m = re.search(r'SCRAPE_RATE",\s*"([\d.]+)"', src)
rate = float(m.group(1)) if m else None
if rate is None:
    sys.exit("could not find the default SCRAPE_RATE")
if rate > 2.0:
    sys.exit(f"default SCRAPE_RATE={rate} exceeds 2 req/s — be kind to the upstream site")
print(f"  ok   default SCRAPE_RATE = {rate} req/s")
PY

echo
if [ "$fail" = "0" ]; then echo "all checks passed"; else echo "some checks failed" >&2; fi
exit "$fail"
