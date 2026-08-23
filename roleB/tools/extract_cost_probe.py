"""속성추출 1건의 실비용 측정 — A에게 넘기는 숫자 (B1-5의 후속).

`llm_quota_probe.py`는 "몇 번 부를 수 있나"를 잰다. 이 스크립트는 **"한 번이 얼마나 드나"**
를 잰다. A의 W3 배치 소요는 후자로 결정된다. 짧은 핑 프롬프트로 잰 숫자는 실제 배치를
전혀 대변하지 못한다 — 프롬프트가 30배 길기 때문이다.

여기서 확인된 것 (2026-08-07 실측, gpt-5.4-nano):
  ⚠️ **`response_format`을 `json_schema` + `strict: true`로 강제하지 않으면 쓸 수 없다.**
     - `json_object`만 켜면 모델이 스키마를 통째로 지어낸다 (필드명이 다른 객체를 반환)
     - 아무것도 안 켜면 JSON이 아닌 것을 뱉는다 (JS 코드 조각이 섞여 나왔다)
     - strict 스키마를 주면 nano도 8/8 필드를 채우고 협찬글 판정도 맞힌다

**프롬프트와 스키마의 소유자는 A다.** 여기 있는 것은 비용을 재기 위한 최소 재현본이며,
A가 `roleA/`에서 실제 배치를 짤 때 이 호출 형식(특히 response_format)만 그대로 가져가면 된다.

사용법
------
    export LLM_API_KEY=...
    export LLM_BASE_URL=https://factchat-cloud.mindlogic.ai/v1/gateway
    export LLM_MODEL=gemini-3.5-flash-lite

    python tools/extract_cost_probe.py --reviews 8 --repeat 2 --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx가 필요하다: pip install -r requirements-dev.txt", file=sys.stderr)
    raise SystemExit(1)

# 앱이 실제로 보내는 UA를 그대로 쓴다. 상수를 복사해 두면 갈린다 —
# 갈린 상태로 W1 실측이 통과했고, prod에서만 403이었다 (docs/LLM_QUOTA.md §0-1).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.llm import USER_AGENT  # noqa: E402

# 고정 어휘는 app/constants.py와 같아야 한다. 여기서 늘리면 A의 추출 결과가 스키마를 벗어난다.
PURPOSE_TAGS = ["데이트", "친구모임", "혼자", "가족", "작업", "회식"]
ATMOSPHERE_TAGS = ["조용한", "활기찬", "감성적인", "트렌디한", "로컬한",
                   "넓은", "뷰가좋은", "아늑한", "이국적인", "가성비"]

# 실제 네이버 블로그 후기의 길이·문체를 흉내 낸 샘플. 협찬글 1건을 섞어 두었다.
SAMPLE_REVIEWS = [
    "이태원 골목 안쪽에 있는 카페인데 창가 자리가 넓고 4인석이 여러 개 있어요. "
    "평일 낮에는 조용해서 노트북 펴기 좋고 콘센트도 자리마다 있습니다. 커피는 8천원대로 좀 있는 편.",
    "주말 오후에 갔더니 30분 정도 웨이팅 했어요. 테라스 자리는 햇빛이 강해서 여름엔 "
    "실내가 낫습니다. 디저트가 맛있어서 다시 갈 듯.",
    "본 포스팅은 업체로부터 제품을 제공받아 작성되었습니다. 분위기가 정말 최고예요! "
    "인테리어가 감성적이고 사진 맛집입니다. 강력 추천드려요!",
    "친구 6명이랑 갔는데 단체석이 없어서 나눠 앉았습니다. 소음은 보통 정도이고 대화는 무리 없어요.",
    "비 오는 날 갔는데 실내가 아늑해서 좋았습니다. 창밖 보는 뷰가 예뻐요. 데이트로 괜찮은 곳.",
    "저녁 8시쯤 가면 한산합니다. 혼자 가서 책 읽기 좋았어요. 가격은 조금 비싼 편이지만 "
    "자리가 편해서 오래 있게 됩니다.",
    "주차는 근처 공영주차장을 써야 합니다. 가게 자체 주차는 없어요.",
    "아이 데리고 갔는데 유아 의자는 없었습니다. 계단이 있어서 유모차는 불편해요.",
    "직장 동료들이랑 점심 후에 들렀는데 열 명은 좀 무리였습니다. 네다섯 명까지가 적당.",
    "인스타에서 보고 갔어요. 사진 찍기 좋은 조명이고 라떼가 맛있었습니다.",
]

# ⚠️ 이 형식이 핵심이다. strict 스키마 없이는 결과를 신뢰할 수 없다.
RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "poi_attributes",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "outdoor_exposure", "group_capacity", "noise_level", "purpose_tags",
            "atmosphere_tags", "price_band", "sentiment_score", "chunk_is_sponsored",
        ],
        "properties": {
            "outdoor_exposure": {"type": ["number", "null"]},
            "group_capacity": {"type": ["integer", "null"]},
            "noise_level": {"type": ["integer", "null"]},
            "purpose_tags": {"type": "array",
                             "items": {"type": "string", "enum": PURPOSE_TAGS}},
            "atmosphere_tags": {"type": "array",
                                "items": {"type": "string", "enum": ATMOSPHERE_TAGS}},
            "price_band": {"type": ["integer", "null"]},
            "sentiment_score": {"type": ["number", "null"]},
            "chunk_is_sponsored": {"type": "array", "items": {"type": "boolean"}},
        },
    },
}

PROMPT_TEMPLATE = """너는 장소 속성 추출기다. 아래 후기들을 읽고 장소의 속성을 JSON으로 출력한다.

규칙
- 후기에 단서가 있으면 반드시 값을 채운다. 단서가 전혀 없는 필드만 null로 둔다.
- purpose_tags / atmosphere_tags 는 주어진 목록 안에서만 고른다. 실제 해당하는 것만 넣는다.
- chunk_is_sponsored 는 후기 개수와 길이가 같은 boolean 배열이다.
  "제공받아 작성", "협찬", "원고료" 등이 있으면 true.
- outdoor_exposure 는 0=완전실내 1=완전야외다. 테라스가 있어도 주 좌석이 실내면 0.3 이하다.
- JSON 외의 텍스트나 코드는 절대 출력하지 않는다.

purpose_tags 후보: {purposes}
atmosphere_tags 후보: {atmospheres}

후기 (총 {n}개):
{body}"""


def build_prompt(n_reviews: int) -> str:
    reviews = (SAMPLE_REVIEWS * 3)[:n_reviews]
    return PROMPT_TEMPLATE.format(
        purposes=", ".join(PURPOSE_TAGS),
        atmospheres=", ".join(ATMOSPHERE_TAGS),
        n=len(reviews),
        body="\n".join(f"[{i + 1}] {r}" for i, r in enumerate(reviews)),
    )


def extract_once(
    client: httpx.Client, base_url: str, model: str, api_key: str, prompt: str
) -> dict[str, Any]:
    started = time.perf_counter()
    r = client.post(
        f"{base_url.rstrip('/')}/chat/completions/",
        headers={"Authorization": f"Bearer {api_key}",
                 # 앱과 **같은 UA로 잰다.** 이게 다르면 재는 경로와 도는 경로가
                 # 갈린다 — 실제로 한 번 갈렸다 (docs/LLM_QUOTA.md §0-1).
                 "User-Agent": USER_AGENT},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
        },
    )
    elapsed = time.perf_counter() - started
    out: dict[str, Any] = {"status": r.status_code, "elapsed_s": round(elapsed, 3)}
    if r.status_code != 200:
        out["error"] = r.text[:200]
        return out

    body = r.json()
    out["usage"] = body.get("usage", {})
    content = body["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
        out["parsed"] = parsed
        out["filled_fields"] = sum(1 for v in parsed.values() if v not in (None, [], {}))
        out["total_fields"] = len(parsed)
    except ValueError as e:
        out["parse_error"] = str(e)
        out["raw"] = content[:300]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="속성추출 1건의 토큰·지연 실측")
    ap.add_argument("--reviews", type=int, default=8, help="POI당 후기 수 (목표 8~10)")
    ap.add_argument("--repeat", type=int, default=2, help="반복 호출 수")
    ap.add_argument("--poi-count", type=int, default=800, help="T1 목표 POI 수")
    ap.add_argument("--confirm", action="store_true", help="실제 호출을 허용한다")
    args = ap.parse_args()

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    if not (api_key and base_url and model):
        print("LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 이 필요하다", file=sys.stderr)
        return 2

    prompt = build_prompt(args.reviews)
    if not args.confirm:
        print(f"실제 호출이 나간다. {model} · 후기 {args.reviews}개 × {args.repeat}회\n"
              f"프롬프트 길이 {len(prompt)}자. 진행하려면 --confirm 을 붙인다.")
        return 0

    results = []
    with httpx.Client(timeout=120.0) as client:
        for i in range(args.repeat):
            res = extract_once(client, base_url, model, api_key, prompt)
            results.append(res)
            u = res.get("usage", {})
            print(f"[{i + 1}/{args.repeat}] {res['status']} {res['elapsed_s']}s "
                  f"tokens {u.get('prompt_tokens')}+{u.get('completion_tokens')}"
                  f"={u.get('total_tokens')} "
                  f"filled {res.get('filled_fields')}/{res.get('total_fields')}")
            if "parse_error" in res:
                print(f"    ⚠️ JSON 파싱 실패: {res['parse_error']}")

    ok = [r for r in results if r["status"] == 200 and "parsed" in r]
    if not ok:
        print("성공한 호출이 없다.")
        return 1

    avg_tokens = sum(r["usage"].get("total_tokens", 0) for r in ok) / len(ok)
    avg_latency = sum(r["elapsed_s"] for r in ok) / len(ok)
    total_calls = args.poi_count

    print("\n--- A의 배치 산정 ---")
    print(f"POI당 토큰   : {avg_tokens:.0f}  (후기 {args.reviews}개 기준)")
    print(f"POI당 지연   : {avg_latency:.2f}s")
    print(f"T1 {total_calls} POI 총 토큰 : {avg_tokens * total_calls / 1000:.0f}K")
    print(f"직렬 소요    : {avg_latency * total_calls / 60:.0f}분")
    print(f"동시 8 소요  : {avg_latency * total_calls / 8 / 60:.0f}분 "
          "(429가 안 나는 범위에서)")
    print("\n※ 일일/크레딧 한도는 게이트웨이가 헤더로 알려주지 않는다. "
          "배치에 누적 호출 카운터를 넣고 끊긴 지점을 기록할 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
