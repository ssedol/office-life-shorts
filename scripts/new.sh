#!/usr/bin/env bash
# 주제 하나로 output/NNNN.json 뼈대를 만든다.
# JSON이 단일 진실이고, 마크다운은 scripts/render.py 가 만든다.
#   ./scripts/new.sh -c A -k 상사 "팀장이 한숨 쉴 때 하면 안 되는 것"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AXIS=""; CATEGORY=""; TOPIC_ID=""

usage() {
  cat <<'USAGE'
사용법: ./scripts/new.sh -c <축> [-k <카테고리>] [-t <주제ID>] "<주제>"

  -c  축 (필수) : A|공감 , B|꿀팁     (C축은 현재 비활성 — config/axes.yaml)
  -k  카테고리   : 상사, 보고문서, 동료, 회식, 연차, 야근, 연봉, 이직, 신입
  -t  주제 ID    : data/topics.yaml 의 id (예: T001)
USAGE
}

while getopts ":c:k:t:h" opt; do
  case "$opt" in
    c) AXIS="$OPTARG" ;;
    k) CATEGORY="$OPTARG" ;;
    t) TOPIC_ID="$OPTARG" ;;
    h) usage; exit 0 ;;
    \?) echo "알 수 없는 옵션: -$OPTARG" >&2; usage; exit 1 ;;
    :)  echo "-$OPTARG 에 값이 필요합니다" >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

TOPIC="${1:-}"
[[ -n "$TOPIC" && -n "$AXIS" ]] || { echo "주제와 -c 축은 필수입니다." >&2; usage; exit 1; }

case "$AXIS" in
  A|a|공감) AXIS="A" ;;
  B|b|꿀팁) AXIS="B" ;;
  C|c|정보) echo "C축(정보)은 현재 비활성입니다. config/axes.yaml 참고." >&2; exit 1 ;;
  *) echo "축은 A|공감, B|꿀팁 중 하나여야 합니다: $AXIS" >&2; exit 1 ;;
esac

mkdir -p "$ROOT/output"
LAST=$(find "$ROOT/output" -maxdepth 1 -name '[0-9][0-9][0-9][0-9].json' -printf '%f\n' 2>/dev/null \
       | sed 's/\.json$//' | sort -n | tail -1)
NEXT=$(printf '%04d' $(( 10#${LAST:-0} + 1 )))
FILE="$ROOT/output/${NEXT}.json"
[[ -e "$FILE" ]] && { echo "이미 존재합니다: $FILE" >&2; exit 1; }

AXIS="$AXIS" CATEGORY="$CATEGORY" TOPIC="$TOPIC" TOPIC_ID="$TOPIC_ID" NEXT="$NEXT" \
python3 - "$FILE" <<'PY'
import json, os, sys, yaml, pathlib
root = pathlib.Path(__file__).resolve()
ax = yaml.safe_load(open(os.path.join(os.path.dirname(sys.argv[1]), "..", "config", "axes.yaml"), encoding="utf-8"))
blocks = [{"id": b["id"], "narration": "", "visual": "", "caption": "", "_role": b["role"]}
          for b in ax["structure"]]
doc = {
    "id": os.environ["NEXT"],
    "topic_id": os.environ["TOPIC_ID"],
    "topic": os.environ["TOPIC"],
    "axis": os.environ["AXIS"],
    "category": os.environ["CATEGORY"],
    "brief": {"situation": "", "emotion_before": "", "emotion_after": "",
              "core_line": "", "cta_question": ""},
    "hook_candidates": [{"pattern": "", "text": ""} for _ in range(3)],
    "hook_chosen": 0,
    "hook_reason": "",
    "blocks": blocks,
    "meta": {"title": "", "hashtags": ["#shorts", "#직장생활", "", "#직장인생존기"],
             "description": "", "pinned_comment": "", "thumbnail_text": "",
             "ai_disclosure": False},
    "production": {"synthetic_voice": False, "synthetic_visual": False, "human_elements": []},
    "status": "draft",
}
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
PY

echo "생성됨: output/${NEXT}.json"
cat <<EOF

다음 단계:
  1) prompts/generate-shorts.md 로 대본 생성 → output/${NEXT}.json 채우기
  2) ./scripts/validate.py output/${NEXT}.json     # 통과해야 다음 단계
  3) ./scripts/render.py   output/${NEXT}.json -w  # 사람이 읽을 마크다운
EOF
