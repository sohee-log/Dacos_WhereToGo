# LLM 한도·비용 실측 (B1-5)

> **상태: 측정 완료 (2026-08-07).** 아래 숫자로 A의 W3 배치 일정을 잡으면 된다.
> 재측정: `tools/llm_quota_probe.py`(처리량) · `tools/extract_cost_probe.py`(1건 실비용)

---

## 결론 세 줄

1. **속성추출 배치는 병목이 아니다.** T1 800 POI가 직렬 31분, 동시 8이면 4분이다.
   PLAN.md §8.2의 "야간 배치 2~3일" 전제는 이제 유효하지 않다.
2. **`response_format`을 `json_schema` + `strict: true`로 강제해야 한다.** 이걸 빼면
   `gpt-5.4-nano`는 스키마를 지어내거나 JSON이 아닌 것을 뱉는다. 모델의 문제가 아니라 형식의 문제다.
3. **일일/크레딧 한도는 알 수 없다.** 게이트웨이가 rate limit 헤더를 내려주지 않는다.
   배치에 누적 호출 카운터를 넣고 끊긴 지점을 기록하는 것 외에 방법이 없다.

---

## 조달 경로

| 항목 | 값 |
|---|---|
| 게이트웨이 | FactChat API Gateway (MindLogic) |
| Base URL | `https://factchat-cloud.mindlogic.ai/v1/gateway` |
| 형식 | **OpenAI Chat Completions 호환** — 경로에 **끝 슬래시 필요** (`/chat/completions/`) |
| 인증 | `Authorization: Bearer <KEY>` 또는 `x-api-key: <KEY>` |
| 채택 모델 | **`gpt-5.4-nano`** (게이트웨이에서 80개 모델 조회 가능) |
| 결제수단 등록 | 불필요 — 팀 조달 키. §0.1 하드 제약 통과 |

> 🔑 **키는 레포 어디에도 없다.** 로컬은 `roleB/.env`(gitignore됨), prod는 Render 환경변수.
> public 레포이므로 예외가 없다.

---

## 측정 1 — 처리량 (`llm_quota_probe.py --seq 15 --burst 12`)

| 항목 | 값 |
|---|---|
| 직렬 15회 | 전부 200. **429 없음** |
| 직렬 지연 (짧은 프롬프트) | 중앙값 1.14s (최소 1.02 / 최대 1.83) |
| **동시 12회** | **전부 200. 벽시계 2.36초** — 동시성 12까지 문제없다 |
| rate limit 헤더 | **없음** (`x-ratelimit-*`, `retry-after` 전부 미제공) |
| 관측 RPM 하한 | 52 (직렬 기준) / 동시성 12면 실효 300+ |

27회 호출 중 429가 0건이다. 분당 상한은 아직 못 찾았고, **상한을 찾겠다고 쿼터를 태울 이유가 없다.**
배치가 실제로 끊기는 지점을 A가 W3에 기록하는 편이 싸다.

## 측정 2 — 속성추출 1건의 실비용 (`extract_cost_probe.py --reviews 9 --repeat 3`)

짧은 핑 프롬프트로 잰 숫자는 배치를 대변하지 못한다. 실제 프롬프트는 30배 길다.

| 항목 | 값 |
|---|---|
| POI당 토큰 | **1,038** (프롬프트 929 + 출력 ~109, 후기 9개 기준) |
| POI당 지연 | **2.3초** |
| 결과 품질 | 8개 필드 중 7~8개 채움. 3회 모두 JSON 파싱 성공 |
| 협찬글 판정 | 9건 중 협찬 1건을 정확히 집어냄 |

**추출 값 샘플** (후기 9건 → nano)

```json
{"outdoor_exposure": 0.2, "group_capacity": 5, "noise_level": 2,
 "price_band": 2, "sentiment_score": 0.7,
 "chunk_is_sponsored": [false,false,true,false,false,false,false,false,false]}
```

테라스가 있지만 주 좌석이 실내인 카페 → `0.2`. "네다섯 명까지가 적당" → `group_capacity 5`.
후기 내용과 일치한다.

---

## A의 W3 배치 산정

| 항목 | 값 |
|---|---|
| T1 800 POI 총 토큰 | **약 830K** |
| 직렬 소요 | **31분** |
| 동시 8 소요 | **4분** |
| T2까지(1,500 POI) 확장 시 | 직렬 58분 / 동시 8이면 7분 |

**시간 제약이 사라졌으므로 T2 확장이 기술적으로 열린다.** 다만 병목이 옮겨갔을 뿐이라는 점이 중요하다.

> 이제 진짜 병목은 **네이버 블로그 리뷰 수집**이다. LLM은 몇 분이지만, POI당 4종 쿼리로
> 800곳을 긁고 상호 매칭 품질을 확인하는 일은 그대로 남아 있다. PLAN.md §8.1이 여전히 최대 리스크다.

---

## A가 그대로 가져갈 호출 형식

```python
{
  "model": "gpt-5.4-nano",
  "messages": [{"role": "user", "content": prompt}],
  "max_tokens": 400,
  "response_format": {                      # ← 이게 없으면 결과를 신뢰할 수 없다
    "type": "json_schema",
    "json_schema": {"name": "poi_attributes", "strict": True, "schema": {...}}
  }
}
```

`tools/extract_cost_probe.py`에 동작하는 스키마 전문이 있다. **프롬프트와 스키마의 소유자는 A다** —
거기 있는 것은 비용 측정용 최소 재현본이고, 호출 형식만 가져가면 된다.

### 실패 모드 (실측으로 확인한 것)

| 설정 | 결과 |
|---|---|
| `response_format` 없음 | JSON이 아닌 것을 뱉는다. JS 코드 조각(`.filter(t => true)`)이 섞여 나왔다 |
| `{"type": "json_object"}`만 | 스키마를 통째로 지어낸다. 필드명이 다른 객체(`places` 배열)를 반환했다 |
| `{"type": "json_object"}` + 스키마를 프롬프트로 설명 | 전 필드 `null` |
| **`json_schema` + `strict: true`** | **8/8 필드 정상** |

---

## 남은 미지수와 대응

| 미지수 | 왜 모르나 | 대응 |
|---|---|---|
| 일일 호출 한도 | 헤더 미제공 | 배치에 누적 카운터 + 429/402 시 정상 종료. `attr_extracted_at IS NULL`로 다음날 재개 |
| 크레딧 잔량 | 게이트웨이가 노출 안 함 | 총 토큰을 로그에 남긴다. T1 전체가 830K이므로 규모 자체는 작다 |
| 동시성 상한 | 12까지만 확인 | 배치 동시성은 **8로 시작**한다. 429가 나면 절반으로 줄인다 |

---

## W5(B) 설명 생성 모델은 아직 미정

속성추출은 **구조화 출력**이라 nano로 충분했지만, 최종 추천의 **한국어 설명 문장 생성**은
성격이 다르다. W5에 nano / `gpt-5.4-mini` / `claude-sonnet-4-6`을 같은 시나리오로 비교해 정한다.

온라인 호출은 어차피 `explanation_cache` 히트 시 0회이고 쿼터 소진 시 템플릿으로 폴백하므로,
여기서 모델을 미리 정할 이유가 없다. **W4까지는 LLM을 한 번도 부르지 않는다.**

---

## 재측정 방법

```powershell
cd roleB
$env:LLM_API_KEY  = "<키>"      # 절대 커밋하지 않는다
$env:LLM_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
$env:LLM_MODEL    = "gpt-5.4-nano"

python tools/llm_quota_probe.py   --seq 15 --burst 12 --confirm
python tools/extract_cost_probe.py --reviews 9 --repeat 3 --confirm
```

두 스크립트 모두 `--confirm` 없이는 호출이 나가지 않는다.
