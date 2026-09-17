#!/usr/bin/env bash
# 나레이션 글자수 확인. 45초 쇼츠 기준 공백 제외 210~240자.
#   ./scripts/count.sh "나레이션 문장"
#   cat draft.txt | ./scripts/count.sh
set -euo pipefail
TEXT="${1:-$(cat)}"
printf '%s' "$TEXT" | python3 -c '
import sys, re
t = sys.stdin.read()
n = len(re.sub(r"\s", "", t))
sec = round(n / 5.0, 1)
print(f"공백 제외: {n}자")
print(f"예상 길이: 약 {sec}초 (초당 5자 기준)")
if n < 210:   print("→ 짧음. 210자 이상으로 늘리세요 (BODY 디테일 추가).")
elif n > 240: print("→ 김. 240자 이하로 줄이세요 (SETUP부터 깎으세요).")
else:         print("→ 적정 ✅")
'
