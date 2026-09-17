#!/usr/bin/env bash
# 주제 하나로 output/ 에 대본 뼈대를 만든다.
#   ./scripts/new.sh -c A "팀장이 한숨 쉴 때 하면 안 되는 것"
#   ./scripts/new.sh -c 꿀팁 -k 보고문서 "보고서 첫 줄 공식"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AXIS=""
CATEGORY=""

usage() {
  cat <<'USAGE'
사용법: ./scripts/new.sh -c <축> [-k <카테고리>] "<주제>"

  -c  축 (필수) : A|공감 , B|꿀팁 , C|정보
  -k  카테고리   : 상사, 보고문서, 동료, 회식, 연차, 야근, 연봉, 이직, 신입 ...
  -h  도움말

예) ./scripts/new.sh -c A -k 상사 "팀장이 한숨 쉴 때 하면 안 되는 것"
USAGE
}

while getopts ":c:k:h" opt; do
  case "$opt" in
    c) AXIS="$OPTARG" ;;
    k) CATEGORY="$OPTARG" ;;
    h) usage; exit 0 ;;
    \?) echo "알 수 없는 옵션: -$OPTARG" >&2; usage; exit 1 ;;
    :) echo "-$OPTARG 에 값이 필요합니다" >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

TOPIC="${1:-}"
if [[ -z "$TOPIC" || -z "$AXIS" ]]; then
  echo "주제와 -c 축은 필수입니다." >&2; usage; exit 1
fi

case "$AXIS" in
  A|a|공감) AXIS_LABEL="A(공감)" ;;
  B|b|꿀팁) AXIS_LABEL="B(꿀팁)" ;;
  C|c|정보) AXIS_LABEL="C(정보)" ;;
  *) echo "축은 A|공감, B|꿀팁, C|정보 중 하나여야 합니다: $AXIS" >&2; exit 1 ;;
esac

mkdir -p "$ROOT/output"

# 다음 회차 번호
LAST=$(find "$ROOT/output" -maxdepth 1 -name '[0-9][0-9][0-9][0-9]-*.md' -printf '%f\n' 2>/dev/null \
       | sed 's/^\([0-9]\{4\}\).*/\1/' | sort -n | tail -1)
NEXT=$(printf '%04d' $(( 10#${LAST:-0} + 1 )))

SLUG=$(echo "$TOPIC" | tr ' /' '--' | tr -d '?!,.:"'"'")
FILE="$ROOT/output/${NEXT}-${SLUG}.md"

if [[ -e "$FILE" ]]; then
  echo "이미 존재합니다: $FILE" >&2; exit 1
fi

TODAY=$(date +%Y-%m-%d)

sed -e "s/^회차: 0000/회차: ${NEXT}/" \
    -e "s/^주제:$/주제: ${TOPIC}/" \
    -e "s|^축:.*|축: ${AXIS_LABEL}|" \
    -e "s/^카테고리:$/카테고리: ${CATEGORY}/" \
    -e "s/^작성일:$/작성일: ${TODAY}/" \
    -e "s/^# {주제}$/# ${TOPIC}/" \
    "$ROOT/templates/script.md" > "$FILE"

echo "생성됨: output/${NEXT}-${SLUG}.md"
echo
echo "다음 단계:"
echo "  1) prompts/generate-shorts.md 의 [입력]을 채워 대본을 뽑는다"
echo "  2) 결과를 위 파일에 붙여넣는다"
echo "  3) docs/02-script-formula.md §5 검수 7문항을 통과시킨다"
