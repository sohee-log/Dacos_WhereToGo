# ROLE B — 추천 엔진 · 백엔드 작업 지시서

> **이 문서를 받은 LLM에게**
> 당신은 이 프로젝트의 **B 역할(추천 엔진 · 백엔드)** 담당자로 작업한다.
> 이 문서만으로 작업이 가능하도록 필요한 계약·스키마·수식이 모두 포함되어 있다.
> 아래 **§1 불변 규칙**을 위반하는 코드는 어떤 이유로도 작성하지 않는다.
> 특히 **R3(리뷰를 온라인 LLM에 태우지 않는다)** 와 **§6.4 옵셔널 항 재정규화**는 자주 틀리는 지점이니 반드시 지킨다.
> 전체 설계 배경은 같은 디렉터리의 `PLAN.md`에 있다. 판단이 갈리면 `PLAN.md`가 상위 문서다.

---

## 0. 프로젝트 한 줄

> **"지금의 나(나이·성향)와 지금의 상황(목적·인원·날씨·시간)에 맞는 용산의 장소를, 실제 리뷰 근거와 함께 3~5곳 추천한다."**

| 항목 | 값 |
|---|---|
| 대상 | 서울 용산구 전역, T1 커버리지 800 POI |
| 기간 | 6주 (W1~W6) |
| 예산 | **0원** — LLM은 무료 티어 가정, **rate limit이 병목** |
| 팀 | A(데이터) · B(추천엔진) · C(프론트·배포) |
| 스택 | FastAPI · PostgreSQL(PostGIS + pgvector) · Render Free |

---

## 1. 불변 규칙 (위반 금지)

### 1.1 설계 3대 결정

| # | 규칙 | 이유 |
|---|---|---|
| **R1** | **협업 필터링(CF)을 쓰지 않는다.** 개인화 근거는 `segment_affinity` 통계다 | 개인 방문 로그가 존재하지 않음 |
| **R2** | **좌표/지역을 먼저 확정하지 않는다.** 처음부터 POI 단위로 후보를 뽑고, 상권 인기도는 점수 항으로만 쓴다 | 경계 밖 후보 소실 + 오차 복구 불가 |
| **R3** | **리뷰를 온라인에서 LLM에 태워 후보를 고르지 않는다.** 리뷰는 A가 배치로 뽑아둔 **구조화 속성**으로 필터·점수를 매기고, LLM은 **최종 3~5개의 근거 인용·설명 생성**에만 쓴다 | 요청당 수백 리뷰를 LLM에 넣으면 응답 10초+·무료 쿼터 즉시 소진 |

### 1.2 무료 티어 규칙

- **임베딩 모델을 서버에 올리지 않는다.** bge-m3는 2GB로 Render Free에서 뜨지 않는다. 쿼리 벡터는 `query_vector_cache`에서 **조회**한다.
- **LLM 호출 전 반드시 `explanation_cache`를 먼저 조회**한다.
- **LLM 없이도 서비스가 돌아야 한다.** 쿼터 소진 시 템플릿 폴백으로 자동 전환.
- 결제수단 등록이 필요한 서비스는 사용 금지.

### 1.3 데이터 취급 규칙

- **`NULL`을 `0`으로 바꾸지 않는다.** 특히 `hotspot_code`가 NULL인 POI(핫스팟 반경 밖)에 `live_*` 점수 0을 주면 **해당 POI들이 구조적으로 전멸**한다. §6.4 재정규화 필수.
- 후보가 비면 **반경을 넓혀 재시도**한다. 빈 배열을 그대로 반환하지 않는다.

---

## 2. 소유 범위

| 구분 | 대상 |
|---|---|
| ✅ **내 소유** | `roleB/` 전체, `openapi.yaml`, 스코어링 로직, RAG |
| 🤝 **공동 (3인 합의)** | `db/migrations/*.sql` — **초안 작성은 B가 하되 변경은 PR + 3인 리뷰** |
| ❌ **건드리지 않음** | `roleA/` (A 소유) · `roleC/` (C 소유) |

**B는 W1에 DDL과 OpenAPI 스펙의 초안을 만들어 팀에 제공하는 책임이 있다.** 이게 늦으면 A와 C가 동시에 막힌다.

---

## 3. 레포 구조 (B 담당 부분)

> **폴더는 역할 기준으로 나뉜다.** `roleA/`(데이터) · `roleB/`(엔진) · `roleC/`(웹).
> `db/`와 `seeds/`는 루트에 두고 공유한다. Render 배포 루트는 `roleB/`다.

```
Dacos_WhereToGo/
├── roleA/                          ← A 소유. 건드리지 않음
├── roleC/                          ← C 소유. 건드리지 않음
├── db/migrations/                  ← 공동 (초안은 B, 변경은 PR + 3인 리뷰)
├── seeds/                          ← A 제공
├── docs/                           ← 설계 문서
└── roleB/                          ← B 소유
    ├── app/
    │   ├── main.py                 # FastAPI 앱, CORS, 레이트리밋
    │   ├── config.py               # 환경변수
    │   ├── db.py                   # 커넥션 풀 (psycopg_pool)
    │   ├── schemas.py              # Pydantic — C와의 계약
    │   ├── constants.py            # 가중치, 어휘, ZONE_BARRIER
    │   ├── routers/
    │   │   ├── onboarding.py       # POST /api/onboarding
    │   │   ├── context.py          # GET  /api/context/now
    │   │   ├── recommend.py        # POST /api/recommend
    │   │   ├── feedback.py         # POST /api/feedback
    │   │   └── poi.py              # GET  /api/poi/{id}
    │   └── services/
    │       ├── retrieval.py        # ① 후보 생성 (PostGIS + 하드필터)
    │       ├── scoring.py          # ② 스코어링 + 재정규화
    │       ├── context_fit.py      # 날씨 비선형 로직
    │       ├── live_signals.py     # citydata 기반 실시간 항
    │       ├── rag.py              # ③ pgvector 검색
    │       ├── explain.py          # LLM 설명 + 캐시 + 템플릿 폴백
    │       └── logging_svc.py      # ④ recommendation_log
    ├── tests/
    ├── openapi.yaml                # C와의 계약. 변경은 PR
    ├── requirements.txt
    └── README.md
```

---

## 4. 데이터 계약 (읽기 전용 — A가 채운다)

### 4.1 내가 읽는 테이블

| 테이블 | 용도 | 채우는 주체 |
|---|---|---|
| `poi` | 후보 생성 · 스코어링 | A |
| `segment_affinity` | 세그먼트 선호도 항 | A |
| `review_chunk` | RAG 인용 | A |
| `hotspot_snapshot` | 실시간 혼잡·날씨·연령구성 | A (15분 폴링) |
| `query_vector_cache` | 쿼리 벡터 (72종) | A |

### 4.2 내가 쓰는 테이블

`user_profile`, `recommendation_log`, `explanation_cache`

### 4.3 핵심 컬럼 의미 (스코어링에서 쓰는 것)

```
poi.outdoor_exposure   REAL 0~1   0=완전실내 1=완전야외   ← 날씨 로직의 축
poi.attr_confidence    REAL 0~1   < 0.3 이면 후보에서 제외
poi.hotspot_code       TEXT NULL  NULL = 핫스팟 반경 밖 → live_* 항 없음
poi.zone               TEXT       itaewon/yongsan_stn/huam/ichon/cheongpa
poi.quality_score      REAL       별점 대체 (감성×언급량, A가 배치 산출)
poi.purpose_tags       TEXT[]     고정 어휘 6종
poi.tag_vector         HALFVEC(1024)
```

### 4.4 고정 어휘 (A·C와 공유 — 임의 확장 금지)

```python
PURPOSE_TAGS    = ["데이트", "친구모임", "혼자", "가족", "작업", "회식"]
ATMOSPHERE_TAGS = ["조용한", "활기찬", "감성적인", "트렌디한", "로컬한", "넓은",
                   "뷰가좋은", "아늑한", "이국적인", "가성비"]
WEATHER_STATES  = ["맑음", "비", "미세먼지나쁨", "폭염한파"]
PARTY_BANDS     = {1: (1,2), 2: (3,4), 3: (5,99)}
ZONES           = ["itaewon", "yongsan_stn", "huam", "ichon", "cheongpa"]
```

---

## 5. API 계약 (C와의 인터페이스 — W1에 확정, 이후 변경은 PR)

| Method | Endpoint | 설명 |
|---|---|---|
| `POST` | `/api/onboarding` | 성별·연령·취향태그 → `user_profile` + `taste_vector` |
| `GET` | `/api/context/now` | 현재/예정 시각 날씨·대기질·혼잡도 |
| `POST` | `/api/recommend` | **메인.** 컨텍스트 → 추천 3~5개 + 근거 |
| `POST` | `/api/feedback` | 클릭·선택·만족도 기록 |
| `GET` | `/api/poi/{id}` | 상세 |
| `GET` | `/health` | UptimeRobot 핑 대상 |

### 5.1 `POST /api/recommend`

```jsonc
// Request
{
  "user_id": "u_123",
  "purpose": "데이트",                       // PURPOSE_TAGS 중 하나
  "party_size": 2,
  "budget_band": 3,                          // 1~4
  "location": { "lat": 37.5340, "lng": 126.9946 },
  "visit_at": "2026-08-03T19:00:00+09:00"
}

// Response
{
  "context": {
    "weather": "비 60%", "pm25_grade": 2, "feels_like": 27.4,
    "hotspot": "이태원 관광특구",
    "congest_now": "약간 붐빔",
    "congest_forecast_at_visit": "붐빔",
    "age_mix_top": "20대 31%"
  },
  "results": [
    {
      "poi_id": "p_00812",
      "name": "○○○",
      "category": "베이커리카페",
      "lat": 37.5341, "lng": 126.9950,
      "distance_m": 430,
      "score": 0.87,
      "score_breakdown": {
        "segment": 0.91, "purpose": 0.88, "taste": 0.79,
        "context": 0.95, "quality": 0.72, "distance": 0.36,
        "live_segment": 0.84, "crowd": 0.50
      },
      "reason": "비 예보가 있어 완전 실내 공간 위주로 골랐습니다. …",
      "evidence": [
        { "text": "비 오는 날 창가 자리에서 보는 뷰가 좋아요", "source": "naver_blog" }
      ],
      "is_exploration": false,
      "explain_mode": "llm"                  // "llm" | "cache" | "template"
    }
  ],
  "log_id": 55123
}
```

**`score_breakdown`과 `explain_mode`를 반드시 반환한다.** 디버깅과 발표 시연 모두에 쓰인다. `live_segment`/`crowd`는 핫스팟 밖 POI면 **키를 생략**한다 (0을 넣지 않는다).

---

## 6. 추천 파이프라인 (B의 핵심 산출물)

```
① RETRIEVAL  후보 200~500  · PostGIS 반경 + 하드필터        · SQL
② RANKING    상위 20       · 7개 항 가중합 + 재정규화        · 산술
③ RAG        최종 3~5      · pgvector 사전필터 + LLM 설명    · LLM
④ LOGGING    전량 기록                                       · DB
```

**설계 원칙:** 각 단계는 앞 단계보다 **10배 비싸고 10배 적은 대상**을 처리한다.

### 6.1 ① 후보 생성 — 하드필터

"틀리면 무조건 실패하는 조건"만 넣는다.

```sql
SELECT poi_id, name, category_l2, zone, hotspot_code, commercial_area_id,
       outdoor_exposure, quality_score, purpose_tags, tag_vector,
       ST_Distance(geom, :user_geom) AS dist_m
FROM poi
WHERE ST_DWithin(geom, :user_geom, :radius_m)          -- 기본 1200m
  AND is_open_at(business_hours, :visit_at)
  AND group_capacity >= :party_size
  AND (:rain_prob < 0.6 OR outdoor_exposure <= 0.7)    -- 우천 하드컷
  AND (:pm_grade  < 4   OR outdoor_exposure <= 0.5)    -- 매우나쁨 하드컷
  AND price_band <= :budget_band
  AND attr_confidence >= 0.3;                          -- 속성 미확보 POI 제외
```

**후보가 30개 미만이면 반경을 1.6배로 확대해 재시도 (최대 2회).** 그래도 부족하면 `attr_confidence` 조건을 0.15로 완화하고 응답에 `"low_confidence": true`를 표시한다. **빈 배열을 반환하지 않는다.**

### 6.2 ② 스코어링 — 가중치

```python
W = {
  "segment_affinity":   0.22,   # 과거 통계 — 내 세그먼트의 상권·업종 소비 강도
  "purpose_match":      0.22,   # 요청 목적 ↔ poi.purpose_tags 일치도
  "taste_similarity":   0.16,   # cosine(user.taste_vector, poi.tag_vector)
  "context_fit":        0.13,   # 날씨·시간 적합도
  "quality":            0.09,   # poi.quality_score
  "live_segment_match": 0.10,   # ★옵셔널 — 지금 또래가 있는가
  "crowd_fit":          0.08,   # ★옵셔널 — 목적 대비 혼잡도
}
PENALTY = {"distance": 0.05}
```

#### 6.2.1 `segment_affinity` 항은 **절대값이 아니라 기준점 대비**다 (2026-08-28 추가)

`segment_affinity.affinity`는 0~1이지만 **품질 점수가 아니라 비중**이다. 상권·업종
하나 안에서 성별2 × 연령6 × 요일2 × 시간대6 = **144칸**에 나눠 담기고 합이 1이 된다.
한 칸의 자연스러운 크기는 1/144 ≈ 0.007이다.

이걸 그대로 항으로 쓰면 **중립값(0.5)보다 구조적으로 낮다.** 실 DB 실측
(2026-08-28 · 이태원 19시 · 20대 여성):

```
후보 307건 중 통계를 가진 274건  →  전부 중립 아래 (중앙값 0.0153, 최댓값 0.0468)

  통계 있음   0.22 × 0.0153 = 0.0034
  통계 없음   0.22 × 0.5    = 0.1100
  ────────────────────────────────────
  개인화 근거를 가진 POI가 0.107점 손해
```

**가중치 0.22가 쉬는 게 아니라 부호가 뒤집혀 있었다.** R1(CF 대신 세그먼트 통계)의
근거가 반대로 작동한 것이고, 화면으로는 "그냥 가까운 곳부터"로만 보인다.

그래서 이번 요청 후보들의 중앙값을 기준점으로 삼는다.

```python
ref  = median(이번 후보들의 affinity)          # 관측값만, 0과 None은 뺀다
term = a / (a + ref)                           # a == ref 이면 정확히 0.5
```

- `a == ref` → 0.5. **"모른다"가 "평균이다"와 같은 뜻**이 된다 (§1.3)
- 원본이 몇 칸으로 쪼개져 있든 **스케일에 무관하다.** 상권분석 축이 또 바뀌어도
  이 항은 손볼 필요가 없다 (이미 한 번 바뀌었다)
- 관측된 `0`은 `0`으로 둔다 — "모른다"가 아니라 **"그 세그먼트는 안 간다"는 관측**이다

> 이 항이 고쳐지기 전에는 `explain.py`의 `> 0.8` 문장("또래 방문 비중이 높은 곳")이
> 실데이터에서 **한 번도 뜬 적이 없었다.** 원시 비중의 최댓값이 0.047이었기 때문이다.

### 6.3 `context_fit` — 비선형 (선형으로 만들지 말 것)

**기온은 U자형, 미세먼지는 등급 임계값에서 행동이 꺾인다.** 이걸 선형 항으로 만들면 로직의 핵심이 사라진다.

```python
def context_fit(poi, wx) -> float:
    s = 1.0
    e = poi.outdoor_exposure

    if wx.rain_prob > 0.3:                          # 비
        s *= (1 - 0.7 * e * min(wx.rain_prob, 1.0))
    if wx.pm25_grade >= 3:                          # 나쁨 이상
        s *= (1 - 0.5 * e)
    if wx.feels_like > 31 or wx.feels_like < -5:    # 폭염 / 한파
        s *= (1 - 0.6 * e)
    if wx.is_clear and 15 <= wx.feels_like <= 25:   # 쾌적 → 야외 보너스
        s *= (1 + 0.4 * e)
    if wx.visit_at.hour >= wx.sunset_hour:          # 일몰 후 야외 감점
        s *= (1 - 0.3 * e)

    return max(0.0, min(s, 1.5))
```

**개인화 훅:** `user_profile.weather_sensitivity`(1~3)로 위 계수를 스케일한다. 민감도 3이면 비 계수를 0.7→0.9로 올린다.

### 6.4 ⚠️ 옵셔널 항 재정규화 (가장 자주 틀리는 곳)

용산 POI의 상당수는 121개 핫스팟 반경 밖이라 `hotspot_code`가 `NULL`이다. 이때 `live_*`에 **0을 주면 핫스팟 밖 POI가 구조적으로 전멸**한다.

```python
def total_score(poi, user, ctx) -> tuple[float, dict]:
    terms = {
        "segment_affinity":   segment_affinity(poi, user, ctx),
        "purpose_match":      purpose_match(poi, ctx),
        "taste_similarity":   taste_similarity(poi, user),
        "context_fit":        context_fit(poi, ctx.weather),
        "quality":            poi.quality_score,
        "live_segment_match": live_segment_match(poi.hotspot, user),   # None 가능
        "crowd_fit":          crowd_fit(poi.hotspot, ctx.purpose, ctx.visit_at),  # None 가능
    }
    avail = {k: v for k, v in terms.items() if v is not None}
    wsum  = sum(W[k] for k in avail)
    score = sum(W[k] * v for k, v in avail.items()) / wsum      # ← 재정규화
    score -= PENALTY["distance"] * distance_penalty(poi, user, ctx)
    return score, avail
```

**테스트 필수:** 핫스팟 밖 POI만 있는 요청과 안쪽 POI만 있는 요청의 점수 스케일이 **같은 범위**에 있는지 확인한다.

### 6.5 실시간 항 (citydata 기반)

```python
def live_segment_match(hotspot, user) -> float | None:
    """지금 이 지역에 사용자 또래가 실제로 얼마나 있는가"""
    if hotspot is None:
        return None                                   # ← 0이 아니라 None
    rate = hotspot.age_rates.get(str(user.age_band_10), 0)
    base = BASELINE_AGE_RATE[user.age_band_10]        # 서울 전체 평균 비율
    return clip(rate / base / 2.0, 0, 1)

def crowd_fit(hotspot, purpose, visit_at) -> float | None:
    """목적에 따라 혼잡이 호재일 수도 악재일 수도 있다"""
    if hotspot is None:
        return None
    lvl = hotspot.forecast_congest_at(visit_at)       # FCST_PPLTN (12시간 예측)
    if purpose in ("데이트", "혼자", "작업"):
        return {"여유": 1.0, "보통": 0.8, "약간 붐빔": 0.5, "붐빔": 0.2}[lvl]
    if purpose in ("친구모임", "회식"):
        return {"여유": 0.6, "보통": 0.9, "약간 붐빔": 1.0, "붐빔": 0.8}[lvl]
    return 0.8
```

> **`hotspot_snapshot`은 A가 15분마다 폴링해 적재한다. B는 DB만 읽는다.** 사용자 요청마다 citydata API를 직접 호출하면 쿼터가 즉시 소진된다.

### 6.6 거리 — zone 배율 (직선거리 금지)

용산은 **남산·한강·경부선 철로**로 생활권이 물리적으로 분절된다. 직선 800m라도 철로 반대편이면 도보 20분이다.

```python
ZONE_BARRIER = {   # (from, to) → 배율. 대칭. W2에 수동 상수표로 채운다
    ("itaewon", "yongsan_stn"): 1.4,
    ("itaewon", "huam"):        1.6,
    ("itaewon", "ichon"):       2.2,
    ("yongsan_stn", "ichon"):   1.1,   # 1정거장 — 오히려 가깝다
    ("huam", "ichon"):          2.5,
    # ... 5×5 대칭 행렬 = 10개 값
}

def distance_penalty(poi, user, ctx) -> float:
    d = haversine(user.geom, poi.geom)
    if user.zone != poi.zone:
        d *= ZONE_BARRIER[normalize_pair(user.zone, poi.zone)]
    d_norm = min(d / 2000.0, 1.0)
    return d_norm * (2.0 if ctx.weather.rain_prob > 0.5 else 1.0)
```

**`ZONE_BARRIER`에 없는 조합이 오면 KeyError로 터진다.** 10개 값을 전부 채우고, 조회는 `normalize_pair`로 정렬해 대칭 처리한다.

### 6.7 탐색 슬롯

최종 결과 중 **1개는 점수 6~20위에서 무작위 선택**한다. 인기 쏠림을 막고, 랭킹 학습에 필요한 로그 다양성을 확보한다. 응답에 `is_exploration: true`로 표시한다.

### 6.8 ③ RAG — 상위 20개에만

```
쿼리 벡터  ← query_vector_cache 조회 (purpose, weather_state, party_band)
             ※ 온라인 임베딩 계산 금지 — 모델이 서버에 없다
   ↓
pgvector 검색  WHERE poi_id IN (상위20)  ← 사전 필터(pre-filtering) 필수
   ↓ POI당 관련 청크 최대 3개 (is_sponsored=false 우선)
   ↓
explanation_cache 조회 → 히트하면 LLM 호출 0회
   ↓ 미스
LLM 호출 → 3~5곳 선정 + 근거 인용
   ↓ 쿼터 소진 시
템플릿 폴백 (§6.9)
```

**사후 필터링(post-filtering)을 쓰면 정확도가 붕괴한다.** 반드시 `poi_id`로 먼저 좁힌 뒤 벡터 검색한다.

**인용 검증:** LLM이 반환한 `evidence.text`가 실제 `review_chunk.text`의 부분 문자열인지 후처리에서 검사한다. 불일치하면 해당 인용을 버리고 원문에서 가장 유사한 청크로 대체한다. **LLM 창작 인용을 그대로 내보내지 않는다.**

### 6.9 LLM 폴백 (무료 티어 필수 안전장치)

```python
def template_reason(poi, wx, ctx, terms) -> str:
    parts = []
    if wx.rain_prob > 0.5 and poi.outdoor_exposure < 0.3:
        parts.append("비 예보가 있어 실내 공간 위주로 골랐습니다")
    if terms.get("segment_affinity", 0) > 0.8:
        parts.append(f"{ctx.age_band}대 {ctx.gender_label}의 이 시간대 방문 비중이 높습니다")
    if terms.get("purpose_match", 0) > 0.8:
        parts.append(f"{ctx.purpose}에 적합하다는 후기가 많습니다")
    if terms.get("crowd_fit", 1) < 0.4:
        parts.append("다만 방문 시각에 다소 붐빌 수 있습니다")
    return ". ".join(parts) + "." if parts else "요청하신 조건에 가장 근접한 장소입니다."
```

**W4 시점에는 이 템플릿만으로 추천 v1이 완결되어야 한다.** LLM은 W5에 얹는다.

---

## 7. 주차별 작업

---

### W1 — 계약 확정 (**A와 C의 대기를 푸는 주**)

**이번 주의 산출물은 코드가 아니라 계약이다.** DDL과 OpenAPI가 늦으면 A와 C가 동시에 막힌다. 목요일까지 끝낸다.

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| B1-1 | **DDL 초안 작성** → 3인 리뷰 | `db/migrations/001_init.sql` | 로컬 Docker에 적용 성공 |
| B1-2 | **OpenAPI 스펙 확정** | `openapi.yaml` | 5개 엔드포인트 + 스키마 |
| B1-3 | Pydantic 모델 | `roleB/app/schemas.py` | openapi.yaml과 일치 |
| B1-4 | **목 API 배포** (하드코딩 응답) | Render prod URL | **C가 즉시 개발 착수 가능** |
| B1-5 | **LLM 무료 티어 한도 실측** | 문서 메모 | 분당/일일 한도 숫자 확정 |

**B1-1 DDL에 반드시 포함할 것**

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- poi, segment_affinity, review_chunk, user_profile,
-- recommendation_log, hotspot_snapshot, hotspot,
-- query_vector_cache, explanation_cache, admin_dong
-- (전체 컬럼 정의는 PLAN.md §3.3.4 · §4 참조)

CREATE INDEX idx_poi_geom   ON poi USING GIST (geom);
CREATE INDEX idx_poi_tagvec ON poi USING hnsw (tag_vector halfvec_cosine_ops);
CREATE INDEX idx_chunk_poi  ON review_chunk (poi_id);
CREATE INDEX idx_chunk_vec  ON review_chunk USING hnsw (embedding halfvec_cosine_ops);
```

`HALFVEC`(2바이트/차원)를 쓴다. `VECTOR`(4바이트) 대비 용량 절반이고, **Supabase Free 500MB 안에 들어가기 위한 필수 결정**이다.

**B1-4 목 API — 반드시 실제 스키마 형태로 반환한다**

C가 이걸 보고 UI를 만든다. 필드가 다르면 W4 통합 때 전부 다시 짜야 한다. `seeds/poi_seed.json`(A 제공)을 읽어 그대로 반환하는 형태가 가장 안전하다.

**B1-5 LLM 한도 실측이 왜 W1인가**
이 숫자로 A의 배치 소요일(§ROLE_A W3)이 결정된다. 늦게 알면 A의 일정이 통째로 밀린다.

---

### W2 — 후보 생성 · 스코어링 골격

🚩 **게이트: 시드 데이터로 `/api/recommend`가 점수 순 리스트를 반환**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| B2-1 | DB 커넥션 풀 | `roleB/app/db.py` | psycopg_pool, Render 재시작 견딤 |
| B2-2 | `retrieval.py` — PostGIS 후보 생성 | 코드 | 반경 확대 재시도 포함 |
| B2-3 | `scoring.py` — 7항 골격 + **재정규화** | 코드 | 옵셔널 항 None 처리 테스트 통과 |
| B2-4 | `ZONE_BARRIER` 10개 값 확정 | `constants.py` | 5개 zone 전 조합 |
| B2-5 | `is_open_at()` SQL 함수 | 마이그레이션 | `business_hours` JSONB 파싱 |

**B2-3 테스트 케이스 (반드시 작성)**

```python
def test_renormalize_when_hotspot_missing():
    """핫스팟 밖 POI와 안쪽 POI의 점수 스케일이 같은 범위여야 한다"""
    inside  = score(poi_with_hotspot)      # 7개 항 전부
    outside = score(poi_without_hotspot)   # 5개 항만
    assert 0 <= outside <= 1
    # 동일 조건이면 두 점수 차이가 0.15 이내
```

---

### W3 — 컨텍스트 · 실시간 신호

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| B3-1 | `context_fit.py` — 비선형 날씨 로직 | 코드 | U자형·임계값 테스트 |
| B3-2 | `live_signals.py` — `hotspot_snapshot` 소비 | 코드 | None 반환 경로 검증 |
| B3-3 | `GET /api/context/now` | 엔드포인트 | citydata + 기상청 병합 |
| B3-4 | `weather_sensitivity` 개인화 훅 | 코드 | 온보딩 5번 문항 반영 |

**B3-3 — 두 소스를 쓰는 이유**

| 시나리오 | 소스 |
|---|---|
| "지금 나갈래" (2시간 이내) | citydata `WEATHER_STTS` |
| "저녁에 갈 건데" (3시간 이상 뒤) | 기상청 단기예보 API |
| 혼잡도 (모든 경우) | citydata `FCST_PPLTN` |

서비스 원칙이 *"실측값이 아니라 방문 예정 시각의 예보"* 이므로 기상청을 버리면 안 된다.

---

### W4 — 추천 v1 완성 (**LLM 호출 0회**)

🚩 **게이트: 실데이터로 추천이 나온다. LLM을 한 번도 부르지 않는다.**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| B4-1 | `/api/recommend` 실동작 | 엔드포인트 | 응답 **300ms 이내**, 결과 5개 |
| B4-2 | 탐색 슬롯 | 코드 | `is_exploration` 표시 |
| B4-3 | `template_reason()` 폴백 | 코드 | `explain_mode: "template"` |
| B4-4 | `recommendation_log` 기록 | 코드 | **노출 후보 전량 + 점수 성분** |
| B4-5 | `/api/feedback`, `/api/onboarding` | 엔드포인트 | C 연동 가능 |

**B4-4 — negative sample을 반드시 남긴다**

```jsonc
"candidates": [
  {"poi_id": "p_001", "rank": 1, "score": 0.87, "terms": {...}, "shown": true},
  {"poi_id": "p_002", "rank": 2, "score": 0.85, "terms": {...}, "shown": true},
  {"poi_id": "p_047", "rank": 21, "score": 0.41, "terms": {...}, "shown": false}
]
```

"노출됐지만 선택되지 않은 것"이 없으면 로그를 아무리 모아도 랭킹 모델 학습이 불가능하다. 6주 안에 학습은 안 하지만, **로그 구조는 지금 만들어둔다.**

**B4-1이 이번 주의 핵심이다.** LLM 없이 완결된 추천이 서야 ⓐ RAG의 실제 기여도를 측정할 수 있고 ⓑ LLM이 죽어도 데모가 가능하다.

---

### W5 — RAG · 설명 생성

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| B5-1 | `rag.py` — pgvector **사전필터** 검색 | 코드 | `poi_id IN (...)` 먼저 |
| B5-2 | `explain.py` — LLM 설명 생성 | 코드 | JSON 스키마 강제 |
| B5-3 | `explanation_cache` 적용 | 코드 | 히트 시 LLM 0회 |
| B5-4 | **인용 원문 검증** | 코드 | 일치율 100% |
| B5-5 | 쿼터 소진 → 템플릿 자동 전환 | 코드 | **강제 테스트로 확인** |
| B5-6 | 레이트 리밋 (IP당 분당 10회) | 미들웨어 | — |

**B5-3 캐시 키**

```python
cache_key = sha256(f"{purpose}|{party_band}|{weather_state}|{zone}|{','.join(sorted(top20_ids))}")
```

데모처럼 시나리오가 반복되는 환경에서는 **히트율이 90%를 넘는다.**

**B5-5 — 폴백은 반드시 강제 테스트한다.** 환경변수로 LLM을 강제 실패시켜 `explain_mode: "template"`으로 정상 응답하는지 확인한다. 이 테스트가 없으면 발표 당일 쿼터가 터졌을 때 서비스 전체가 500을 뱉는다.

---

### W6 — 튜닝 · 평가

| # | 작업 | 산출물 |
|---|---|---|
| B6-1 | 가중치 1차 조정 | C의 시나리오 20개 결과 기반 |
| B6-2 | 응답 성능 점검 | p95 지연, 쿼리 플랜 확인 |
| B6-3 | LLM-as-judge 평가 | 시나리오별 적합도 점수 |
| B6-4 | **발표 전날 캐시 워밍 스크립트** | 시나리오 20개 사전 호출 |

**B6-4가 발표 사고 방지의 핵심이다.** 전날 밤 `explanation_cache`를 채워두면 발표 중 LLM 호출이 0회가 되어 쿼터·네트워크 사고가 원천 차단된다.

---

## 8. 자주 하는 실수 (체크리스트)

- [ ] `hotspot_code`가 NULL일 때 `live_*`에 **0을 넣지 않았는가** (→ None + 재정규화)
- [ ] `context_fit`을 선형 가중합으로 만들지 않았는가 (U자형·임계값 유지)
- [ ] 거리에 **직선거리만** 쓰지 않았는가 (zone 배율 필수)
- [ ] `ZONE_BARRIER` 10개 조합을 전부 채웠는가 (KeyError 방지)
- [ ] pgvector 검색에서 **사전 필터**를 했는가 (사후 필터 금지)
- [ ] 온라인에서 **임베딩을 계산**하려 하지 않았는가 (`query_vector_cache` 조회)
- [ ] LLM 호출 전 `explanation_cache`를 조회했는가
- [ ] 인용문이 실제 `review_chunk.text`의 부분 문자열인지 검증했는가
- [ ] `recommendation_log`에 **노출됐지만 선택 안 된 후보**를 남겼는가
- [ ] 후보가 부족할 때 빈 배열을 반환하지 않고 반경을 넓혔는가
- [ ] 스키마를 혼자 바꾸지 않았는가 (PR + 3인 리뷰)

---

## 9. 로컬 실행

```powershell
docker run -d --name yongsan-db -p 5432:5432 `
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=yongsan `
  pgvector/pgvector:pg16

psql -h localhost -U postgres -d yongsan -f db/migrations/001_init.sql
python -m roleA.jobs.load_seeds          # A가 만든 시드 적재

cd roleB
uvicorn app.main:app --reload --port 8000
pytest tests/ -v
```

---

## 10. 막혔을 때 판단 기준

| 상황 | 판단 |
|---|---|
| A의 실데이터가 늦다 | **시드로 계속 간다.** 실데이터 대기는 W4까지 허용되지 않는다 |
| LLM 쿼터가 부족하다 | 템플릿 폴백 비중을 늘린다. **v1이 이미 완결이므로 서비스는 죽지 않는다** |
| 응답이 300ms를 넘는다 | 후보 수를 줄인다(반경 축소) → 인덱스 확인 → 그래도 안 되면 상위 N을 20→12로 |
| 스코어링 가중치를 모르겠다 | 문서 값 그대로 간다. **W6에 실측으로 조정한다.** 미리 고민하지 않는다 |
| 일정이 밀린다 | B5(RAG)의 인용 검증 → LLM-as-judge 순으로 버린다. **B4(v1)는 절대 못 버린다** |
