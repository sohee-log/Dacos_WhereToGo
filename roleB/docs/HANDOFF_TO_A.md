# B → A 인수 메모 (W1~W6)

> 작성 2026-08-10 · 보내는 사람 B(추천 엔진) · 받는 사람 A(데이터)
> 스키마 원본은 [`db/migrations/`](../../db/migrations)다. 어휘 원본은
> [`roleB/app/constants.py`](../app/constants.py)다. 이 문서와 어긋나면 **그쪽이 맞다.**

---

## 한 줄

**엔진은 다 됐다. 지금 막힌 것은 데이터다.** 그리고 데이터가 비어도 **에러가 나지
않는다** — 조용히 중립값으로 계산되고 순위만 밋밋해진다. 그래서 무엇이 비었을 때
무엇이 죽는지를 이 문서에 적는다.

---

## 0. 가장 중요한 숫자 하나

현재 시드로 추천을 돌리면 **가용 가중치의 약 57%가 모든 POI에서 같은 값(0.5)** 이다.

| 항 | 가중치 | 지금 상태 |
|---|---|---|
| `segment_affinity` | 0.22 | ❌ **중립** — `poi.commercial_area_id`가 0/100 |
| `purpose_match` | 0.22 | ✅ 동작 |
| `taste_similarity` | 0.16 | ❌ **중립** — `poi.tag_vector` 없음 · `tag_embedding` 비어 있음 |
| `context_fit` | 0.13 | ✅ 동작 |
| `quality` | 0.09 | ❌ **중립** — `poi.quality_score` 없음 |
| `live_segment_match` | 0.10 | ⬜ 관측 불가 — `poi.hotspot_code`가 0/100 (재정규화됨) |
| `crowd_fit` | 0.08 | ⬜ 위와 같음 |

즉 **지금 순위를 실제로 만드는 것은 `purpose_match` + `context_fit` + 거리뿐**이다.
"당신 세그먼트가 이 시간대에 실제로 소비하는 곳"이라는 §1.3 차별점 1번은
**아직 한 번도 계산된 적이 없다.**

우선순위는 여기서 나온다 — **`commercial_area_id` → `tag_embedding` → `quality_score` → `hotspot_code`.**

---

## 1. 지금 시드 상태 (실측)

`seeds/poi_seed.json` 100행 · `seeds/review_seed.json` 200청크를 그대로 읽은 결과다.

### 잘 채워져 있는 것 ✅

| 컬럼 | 상태 |
|---|---|
| `zone` | 100/100 · 5개 zone에 20씩 고르게 |
| `outdoor_exposure` | 100/100 · 0.01~0.98로 스펙트럼이 넓다 |
| `price_band` · `group_capacity` | 100/100 |
| `attr_confidence` | 100/100 · 0.41~0.90 (하드필터 0.3을 전부 통과) |
| `purpose_tags` · `atmosphere_tags` | 100/100 · **어휘가 정확히 고정 6종/10종과 일치** |

어휘가 하나도 어긋나지 않았다. LLM 추출에서 가장 자주 깨지는 지점인데 깨끗하다.

### 비어 있는 것 ❌

| 컬럼 | 채움 | 비면 무슨 일이 |
|---|---|---|
| `poi.commercial_area_id` | **0/100** | `segment_affinity` 조인 자체가 불가능 → 가중치 0.22가 상수 |
| `poi.tag_vector` | **없음** | 취향 유사도 0.16이 상수 |
| `poi.quality_score` | **없음** | 품질 0.09가 상수 |
| `poi.hotspot_code` | **0/100** | 실시간 항 0.18이 항상 관측 불가 → 배너의 혼잡·연령 줄이 통째로 안 뜬다 |
| `poi.business_hours` | 0/100 | `is_open_at`이 TRUE를 반환한다(의도된 안전장치). 다만 **영업 종료한 곳이 후보에 남는다** |
| `review_chunk.embedding` | **0/200** | 인용은 나가지만 **벡터 정렬이 안 된다** — "요청에 맞는 문장"이 아니라 "최신 비협찬 문장"이 뽑힌다 |

> `sentiment_score`(0~1)와 `mention_count`는 채워져 있다. `quality_score`는
> **이 둘로 계산하는 배치 산출값**이라 시드에 없는 게 맞다 — `compute_quality`를 돌리면 된다.

---

## 2. B가 읽는 테이블과 정확한 규약

### 2-1. `poi` — 후보 백본

B가 쓰는 컬럼과 규칙이다.

| 컬럼 | 규칙 |
|---|---|
| `geom` | `GEOGRAPHY(POINT,4326)`. B가 `ST_DWithin`으로 미터 단위 반경 필터를 건다 |
| `hotspot_code` | **1km 밖은 반드시 NULL.** 임의로 채우면 실시간 신호가 거짓이 된다 |
| `attr_confidence` | `< 0.3`이면 후보에서 자동 제외. 별도 분기 코드가 없다 |
| `outdoor_exposure` | ⚠️ **DDL 기본값이 0.0 = "완전 실내"다.** 안 채우면 모든 POI가 실내로 취급되어 **비가 와도 후보가 안 바뀐다** — 차별점 2번이 통째로 죽는다 |
| `zone` | 거리 배율(`ZONE_BARRIER`)의 키. NULL이면 배율 1.0(중립)이라 "철로 반대편" 보정이 사라진다 |
| `commercial_area_id` | `segment_affinity` 조인 키. **§0의 1순위** |
| `price_band` | NULL이면 예산 필터를 통과시킨다(정보 없음을 부적합으로 바꾸지 않는다) |
| `business_hours` | `{"mon":["10:00","22:00"], ...}`. 자정 넘김(`["18:00","02:00"]`)도 처리된다. NULL이면 항상 영업중으로 본다 |
| `tag_vector` | `HALFVEC(1024)`. **`tag_embedding`과 반드시 같은 임베딩 공간**이어야 코사인이 의미를 갖는다 |

### 2-2. `segment_affinity` — 조회 축을 정확히 맞춰야 한다

B가 던지는 쿼리는 이렇다.

> ⚠️ **2026-08-28 정정 — 두 축이 바뀌었다.** 이전 규약(`age_band` 5세 단위 ·
> `hour_band = 시//4`)은 원본 데이터를 열어 보기 전의 가정이었다. 실제 상권분석
> 추정매출은 **연령 10년 단위 · 시간대 불균등 6구간**으로 제공된다. 엔진을 원본에
> 맞췄다(`app/constants.py`). **A는 원본을 그대로 집계해 넣으면 된다 — 변환 불필요.**

```sql
WHERE commercial_area_id = ANY(...) AND category_l2 = ANY(...)
  AND gender = 'F' AND age_band = ANY(ARRAY[20])
  AND dow_type = 0 AND hour_band = 4
```

| 축 | B의 규약 |
|---|---|
| `gender` | `'M'` / `'F'` |
| `age_band` | **10년 단위**(10 · 20 · 30 · 40 · 50 · 60). 원본의 "10대/20대/…"를 그대로 쓴다. `user_profile.age_band`(온보딩)와 같은 축이라 변환이 없다. **60대 이상은 `60`으로 접는다** |
| `dow_type` | `0`=평일 · `1`=주말. **토·일이 주말** |
| `hour_band` | 원본의 **불균등 6구간을 그대로**. `0`=00\~06 · `1`=06\~11 · `2`=11\~14 · `3`=14\~17 · `4`=17\~21 · `5`=21\~24. **`시 // 4`로 계산하지 말 것** |
| `affinity` | 0~1 정규화. `CHECK` 제약이 걸려 있으니 원본 매출을 그대로 넣으면 INSERT가 실패한다 |
| `category_l2` | `poi.category_l2`와 **문자열이 정확히 같아야** 조인된다. 업종코드 매핑이 여기서 갈린다 |

**축이 어긋나면 에러가 안 난다.** 조회가 0행이 되고 affinity 항(가중치 0.22,
단일 최대)이 조용히 중립값으로 접힌다. 화면으로도 로그로도 구분이 안 된다.
그래서 `db/migrations/003_segment_axis.sql`로 `age_band`에 `CHECK`를 걸어 뒀다 —
5세 단위로 넣으면 **INSERT가 실패**한다. 조용한 0행보다 시끄러운 실패가 낫다.
적재 전에 `psql "$DATABASE_URL" -f db/migrations/003_segment_axis.sql`을 한 번 돌린다.

### 2-2-1. `build_affinity.py` — 집계 초안 (A4-3)

축을 확정했으니 남은 건 집계다. 아래는 **원본 컬럼명만 맞추면 그대로 도는**
초안이다. 상권분석 추정매출 CSV를 스테이징 테이블(`raw_sales`)에 올려 두고
쓰는 것을 전제한다.

**핵심은 한 줄이다 — 매출액을 넣지 말고 비중으로 정규화한다.**
`affinity`에 `CHECK (0~1)`이 걸려 있어 원본 매출을 그대로 넣으면 INSERT가 실패한다.

```sql
INSERT INTO segment_affinity
    (commercial_area_id, category_l2, gender, age_band, dow_type, hour_band,
     affinity, sample_weight)
SELECT
    r.commercial_area_id,
    r.category_l2,
    r.gender,
    r.age_band,
    r.dow_type,
    r.hour_band,
    -- 같은 (상권 × 업종) 안에서의 비중. 상권 규모 차이를 여기서 지운다.
    -- 이걸 안 하면 큰 상권의 모든 세그먼트가 무조건 높게 나온다.
    r.sales / NULLIF(SUM(r.sales) OVER (
        PARTITION BY r.commercial_area_id, r.category_l2
    ), 0)                                   AS affinity,
    r.sales_cnt                             AS sample_weight
FROM raw_sales r
WHERE r.sales IS NOT NULL AND r.sales > 0
ON CONFLICT (commercial_area_id, category_l2, gender, age_band, dow_type, hour_band)
DO UPDATE SET affinity      = EXCLUDED.affinity,
              sample_weight = EXCLUDED.sample_weight;
```

**원본 → 축 매핑에서 조심할 것**

| 원본 | 넣을 값 | 주의 |
|---|---|---|
| 남성/여성 매출 컬럼이 **가로로** 나뉜 형태 | `gender` `'M'`/`'F'` | 언피벗(melt)이 먼저다. 컬럼을 행으로 돌린 뒤 집계한다 |
| `연령대_10_매출_금액` … `연령대_60_이상_매출_금액` | `age_band` 10/20/…/60 | **60대 이상은 `60`으로 접는다.** 70을 넣으면 `CHECK` 위반 |
| `시간대_00_06_매출_금액` … `시간대_21_24_매출_금액` | `hour_band` 0…5 | 컬럼 순서대로 0~5다. **`시 // 4`로 계산하지 말 것** |
| 주중/주말 매출 컬럼 | `dow_type` 0/1 | 토·일이 주말 |
| 업종코드/업종명 | `category_l2` | **`poi.category_l2`와 문자열이 정확히 같아야** 조인된다. 여기서 제일 많이 깨진다 |

**적재 후 자가 점검** — 엔진의 조회 축을 그대로 걸어 본다. 0행이면 축이 어긋난 것이다.

```sql
-- ① 축 값이 규약 안에 있나 (전부 0행이어야 정상)
SELECT DISTINCT age_band  FROM segment_affinity
EXCEPT SELECT unnest(ARRAY[10,20,30,40,50,60]);
SELECT DISTINCT hour_band FROM segment_affinity WHERE hour_band NOT BETWEEN 0 AND 5;
SELECT DISTINCT gender    FROM segment_affinity WHERE gender NOT IN ('M','F');

-- ② 업종 문자열이 poi와 맞나 (0행이어야 정상 — 여기서 제일 많이 깨진다)
SELECT DISTINCT category_l2 FROM segment_affinity
EXCEPT SELECT DISTINCT category_l2 FROM poi;

-- ③ 실제로 엔진 쿼리가 행을 주나 (0이면 위 셋 중 하나가 어긋난 것)
SELECT count(DISTINCT p.poi_id) AS matched, (SELECT count(*) FROM poi) AS total
FROM poi p
JOIN segment_affinity s ON s.commercial_area_id = p.commercial_area_id
                       AND s.category_l2 = p.category_l2
WHERE s.gender IN ('M','F') AND s.age_band = ANY(ARRAY[10,20,30,40,50,60])
  AND s.dow_type IN (0,1)   AND s.hour_band BETWEEN 0 AND 5;

-- ④ 비중이 상권·업종별로 1에 가깝게 합쳐지나 (정규화가 맞았나)
SELECT commercial_area_id, category_l2, round(SUM(affinity)::numeric, 3) AS s
FROM segment_affinity GROUP BY 1, 2 HAVING SUM(affinity) < 0.95 OR SUM(affinity) > 1.05
LIMIT 20;
```

또는 엔진 도구가 같은 걸 한 번에 답한다 — **"세그먼트 축 점검" 섹션**을 본다.

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"
python -m tools.check_data_readiness
```

### 2-2-2. `tag_embedding` 16행 — 투입 대비 효과가 제일 크다

임베딩 **16번**이면 끝난다(분위기 10 + 목적 6). 이게 비어 있으면 온보딩의
`taste_vector`가 NULL이 되고 취향 항 **0.16이 통째로 상수**다.

```python
from app.constants import ATMOSPHERE_TAGS, PURPOSE_TAGS   # 어휘는 여기가 원본이다
rows = [(t, "atmosphere") for t in ATMOSPHERE_TAGS] + [(t, "purpose") for t in PURPOSE_TAGS]
# embedding = bge-m3(tag)  ·  poi.tag_vector 와 **같은 모델·같은 공간**이어야 한다
# INSERT INTO tag_embedding (tag, kind, embedding) VALUES (%s, %s, %s)
```

어휘를 임의로 늘리면 온보딩에서 조회되지 않고 **조용히 빠진다.** 늘리려면
`roleB/app/constants.py`와 `openapi.yaml`을 함께 고쳐야 하고, 그건 3인 합의다.

### 2-3. `hotspot_snapshot` — 15분 폴링 (A3-4)

B는 `hotspot_latest` 뷰만 읽는다. **요청마다 citydata를 부르지 않는다.**

| 컬럼 | 규약 |
|---|---|
| `congest_lvl` | 고정 어휘 4종만: `여유` `보통` `약간 붐빔` `붐빔`. 밖의 값은 버려진다 |
| `age_rates` | `{"20": 31.2, ...}`. **퍼센트(31.2)와 비율(0.312) 둘 다 받는다** |
| `weather` | **WEATHER_STTS 원본 키·문자열 그대로** 넣으면 된다. 파서가 `"-"`·`""`·`"1.5mm"`를 전부 받아낸다. 소문자로 정규화해 넣어도 읽힌다 |
| `fcst` | 🔴 **여기가 핵심이다.** 아래 참조 |
| `observed_at` | **40분** 이상 오래되면 stale로 잡힌다. 폴링이 죽으면 여기서 보인다 |

🔴 **`fcst`를 반드시 채워달라.** W3부터 혼잡도는 실황이 아니라 `FCST_PPLTN`의
**방문 예정 시각 슬롯**을 쓴다. 비면 실황으로 물러서고, 그러면 배너의
*"지금 약간 붐빔 → 19시 붐빔 예상"* 이 사라진다. 이게 발표에서 가장 강한 카드다.

```jsonc
[
  {"FCST_TIME": "2026-08-03 19:00", "FCST_CONGEST_LVL": "붐빔"},
  {"FCST_TIME": "2026-08-03 21:00", "FCST_CONGEST_LVL": "약간 붐빔"}
]
```
원본 배열을 그대로 넣으면 된다. B가 방문 시각에 가장 가까운 슬롯(±90분)을 고른다.

### 2-4. `review_chunk` — RAG 인용

| 컬럼 | 규약 |
|---|---|
| `text` | 최대 300자. **인용에 그대로 나가는 문장**이다. 요약문이 아니라 원문 발췌여야 한다 |
| `embedding` | `HALFVEC(1024)`. 없어도 인용은 나가지만 벡터 정렬이 안 된다 |
| `is_sponsored` | ⚠️ **정렬 첫 키다.** 협찬 글은 인용에서 뒤로 밀린다. 이 판정이 없으면 광고 문장이 대표 인용으로 뜬다 |
| `written_at` | 벡터가 없을 때의 정렬 키(최신순) |

현재 시드는 200청크 중 **19건이 협찬 판정**되어 있다. 판정 자체는 잘 돌고 있다.

### 2-5. `query_vector_cache` — 72행

목적 6 × 날씨 4 × 인원밴드 3. **온라인에서 임베딩하지 않기 위한 장치**다(§1.2).

- `weather_state` 어휘: `맑음` `비` `미세먼지나쁨` `폭염한파`
- `party_band`: 1=(1~2인) · 2=(3~4인) · 3=(5인 이상)
- `query_text`는 `NOT NULL`이다. 임베딩의 원문을 그대로 넣으면 된다

없으면 인용이 전부 비-벡터 경로(최신 비협찬)로 간다.

### 2-6. `tag_embedding` — 16행 (신규 · `002_tag_embedding.sql`)

**W4에 추가한 테이블이다.** 온보딩의 `taste_vector`를 만들려면 태그별 벡터가
필요한데 담을 곳이 없었다. 임베딩 모델을 서버에 올릴 수 없어서(bge-m3 2GB, §1.2)
A가 배치로 한 번 만들어 두면 온라인에서는 평균만 낸다 — `query_vector_cache`와 같은 발상이다.

```sql
INSERT INTO tag_embedding (tag, kind, embedding) VALUES
  ('조용한', 'atmosphere', '[...]'::halfvec(1024)),
  ('데이트', 'purpose',    '[...]'::halfvec(1024));
```

- 분위기 10 + 목적 6 = **16행.** `ATMOSPHERE_TAGS`·`PURPOSE_TAGS`와 정확히 같아야 한다
- **`poi.tag_vector`와 같은 임베딩 공간**이어야 코사인이 의미를 갖는다
- ⚠️ 공동 소유 영역이라 **적용 전에 3인 리뷰**가 필요하다 (추가만 하고 기존 테이블은 안 건드린다)

### 2-7. `admin_dong` · `commercial_area` · `hotspot`

| 테이블 | B의 사용처 | 비면 |
|---|---|---|
| `admin_dong` | 사용자 좌표 → `zone` 판정 (거리 배율의 기준점) | 배율 1.0, 체감거리 보정이 사라진다 |
| `commercial_area` | `poi.commercial_area_id`의 참조 대상(FK) | POI 적재 시 FK 위반이 난다 |
| `hotspot` | 사용자 최근접 지점 → 배너의 `hotspot` 이름 | 배너에 지역명이 안 뜬다 |

`hotspot`은 **용산 해당 5~7개**만 넣으면 된다. 코드·이름은 `서울시 주요 121장소 목록.xlsx` 기준이다.

---

## 3. B가 A에게 이미 준 것

### 3-1. LLM 실측 — 배치 일정 전제가 바뀌었다

[`docs/LLM_QUOTA.md`](LLM_QUOTA.md)에 전문이 있다. 요약:

| 항목 | 값 |
|---|---|
| POI당 | **1,038토큰 / 2.3초** (후기 9건 기준) |
| T1 800 POI | **직렬 31분 · 동시 8이면 4분** |
| 동시성 | 12까지 429 없음. **8로 시작**하고 429가 나면 절반으로 |
| rate limit 헤더 | 없음 → 배치에 누적 카운터를 넣고 끊긴 지점을 기록해야 한다 |

> **PLAN §8.2의 "야간 배치 2~3일" 전제는 폐기해도 된다.** 시간 제약이 사라졌으므로
> T2 확장(1,500 POI, 동시 8이면 7분)이 기술적으로 열린다. 다만 병목이 옮겨간 것뿐이다 —
> **진짜 병목은 네이버 블로그 수집**이고 PLAN §8.1이 여전히 최대 리스크다.

🔴 **`response_format`을 `json_schema` + `strict: true`로 강제해야 한다.**
실측한 실패 모드다.

| 설정 | 결과 |
|---|---|
| `response_format` 없음 | JSON이 아닌 것을 뱉는다 (JS 코드 조각이 섞여 나왔다) |
| `{"type":"json_object"}`만 | **스키마를 통째로 지어낸다** |
| `json_schema` + `strict:true` | 8/8 필드 정상 |

`strict: true`는 모든 필드가 `required`이고 `additionalProperties: false`여야 한다.
안 지키면 게이트웨이가 400을 준다.

### 3-2. 스키마와 개발 도구

- `db/migrations/001_init.sql` · `002_tag_embedding.sql` — 초안은 B가 쓰되 **변경은 PR + 3인 리뷰**
- `roleB/tools/load_seed_db.py` — **개발용**이다. 운영 적재는 A(`roleA/jobs/`)의 몫이라
  시드에 있는 컬럼만 채운다. `--demo-vectors`로 가짜 벡터를 넣어 `<=>`·halfvec 경로를
  켜볼 수 있다(의미는 없고 구조만 진짜다)
- `is_open_at()` SQL 함수는 실 DB에서 4케이스 확인 완료 (NULL→TRUE / 영업중 / 종료 / 자정 넘김)

---

## 4. B가 A에게 부탁하는 것

### 🔴 4-1. `poi.commercial_area_id` 공간조인 (§0의 1순위)

이게 없으면 **개인화의 근거(가중치 0.22)가 통째로 상수**다. CF를 버리고 세그먼트
통계를 택한 §1.1의 결정이 아직 한 번도 검증되지 않았다.

### 🔴 4-2. `tag_embedding` 16행

임베딩 16번이면 끝난다. 이것만으로 취향 항(0.16)이 살아난다.

### 🟠 4-3. `hotspot_snapshot.fcst`

배너의 *"19시 붐빔 예상"* 이 여기서 나온다.

### 🟡 4-4. `BASELINE_AGE_RATE` 실측치

`app/constants.py`의 이 값은 **내가 넣은 잠정치**다.

```python
BASELINE_AGE_RATE = {10: 0.10, 20: 0.22, 30: 0.20, 40: 0.18, 50: 0.16, 60: 0.14}
```

`live_segment_match`의 분모라서(= "서울 전체 평균 대비 또래가 얼마나 많은가")
틀리면 실시간 세그먼트 항이 체계적으로 치우친다. **A가 citydata를 15분마다
폴링하니 며칠이면 실측 평균이 나온다.** 나오면 알려달라 — 상수만 갈면 된다.

### 🟡 4-5. 어휘를 늘리지 말 것

`purpose_tags`·`atmosphere_tags`·`congest_lvl`·`weather_state`는 A·B·C가 공유한다.
하나만 늘리면 **조회에서 조용히 빠진다**(에러가 아니라 매칭 실패다).
늘려야 하면 3인 합의 + `openapi.yaml` 동시 수정이다.

---

## 5. 확인하는 법

A가 적재한 뒤 이 쿼리들로 스스로 점검할 수 있다.

```sql
-- 조인 키가 얼마나 채워졌나 (§0의 1순위)
SELECT count(*) AS total,
       count(commercial_area_id) AS with_area,
       count(hotspot_code)       AS in_hotspot,
       count(quality_score)      AS with_quality,
       count(tag_vector)         AS with_vector
FROM poi;

-- 어휘가 새지 않았나 (결과가 0행이어야 정상)
SELECT DISTINCT unnest(purpose_tags) AS tag FROM poi
EXCEPT SELECT unnest(ARRAY['데이트','친구모임','혼자','가족','작업','회식']);

-- 폴링이 살아 있나 (40분 넘으면 stale)
SELECT hotspot_code, observed_at, now() - observed_at AS age,
       jsonb_array_length(fcst) AS fcst_slots
FROM hotspot_latest;

-- 캐시가 다 찼나
SELECT count(*) FROM query_vector_cache;   -- 72
SELECT kind, count(*) FROM tag_embedding GROUP BY kind;  -- atmosphere 10 / purpose 6
```

엔진 쪽 통합 테스트도 그대로 쓸 수 있다. DB만 있으면 된다.

```powershell
cd roleB
$env:TEST_DATABASE_URL = "postgresql://..."
pytest tests/test_live_db.py -v
```

`hotspot_code`가 전부 NULL이거나 전부 채워져 있으면 일부 테스트가 skip된다 —
**그 자체가 "한쪽 경로를 검증하지 못했다"는 신호**다.

---

## 6. 한 장 체크리스트

- [ ] `commercial_area` 폴리곤 적재 → `poi.commercial_area_id` 공간조인 🔴
- [ ] `tag_embedding` 16행 (분위기 10 + 목적 6, `poi.tag_vector`와 같은 공간) 🔴
- [ ] `segment_affinity` — **10년 단위** age_band · **불균등 6구간** hour_band(00\~06/06\~11/11\~14/14\~17/17\~21/21\~24) · affinity 0~1 정규화
- [ ] `compute_quality` → `poi.quality_score`
- [ ] `poi.hotspot_code` 매핑 (**1km 밖은 NULL 유지**)
- [ ] `hotspot_snapshot.fcst` + `weather` 원본 그대로
- [ ] `review_chunk.embedding` (bge-m3, halfvec)
- [ ] `query_vector_cache` 72행
- [ ] `admin_dong.zone` (사용자 zone 판정)
- [ ] `poi.business_hours` (없어도 돌지만 영업 종료 매장이 후보에 남는다)
- [ ] `BASELINE_AGE_RATE` 실측치 회신
- [ ] LLM 배치는 `json_schema` + `strict: true` · 동시성 8 시작 · 누적 카운터

막히면 `db/migrations/`와 `app/constants.py`를 먼저 보고, 그래도 다르면 B에게.
스키마 변경은 PR + 3인 리뷰다.

---

## 7. 추가 (2026-08-17) — W2 적재분을 보고

POI 6,644건 · `zone`/`dong` 100% · 상권 95.64%. 게이트 전부 넘겼다. 그 위에서
확인한 것과 부탁 하나.

### 7-1. 자가 점검이 이제 스크립트다

위 체크리스트의 "무엇이 비면 무엇이 죽는가"를 실행 가능한 형태로 만들었다.
적재하고 나서 한 번 돌리면 된다.

```powershell
$env:DATABASE_URL = "postgresql://..."
python -m tools.check_data_readiness      # roleB/ 에서
```

**"순위를 실제로 움직이는 가중치 몇 %"** 를 마지막에 찍는다. 항이 비면 전
POI가 같은 값이라 기여가 적은 게 아니라 **정확히 0**이다. 채우기 전후로
이 숫자가 얼마나 올라가는지 보면 어느 작업이 실제로 추천을 바꾸는지 보인다.

### 7-2. `attr_confidence`는 계약대로다 — 순서만 맞추면 된다

지금 전 건 0인데, 속성 추출이 A3-2/A4-1이니 이게 맞다. 다만 B의 후보 필터가
0.30이라 **이 상태로 `MOCK_MODE=false`를 내리면 추천이 최근접 폴백(순위 없는
3건)으로 주저앉는다.** 에러가 아니라 200이 나가면서 순위만 사라진다.

B 쪽 임계값을 환경변수로 빼 뒀으니(`ATTR_CONFIDENCE_MIN`) 화면을 먼저 봐야
하면 내렸다가 추출 후 되돌리면 된다. **전환 시점만 셋이 합의하면 된다.**

### 7-3. 시드에 두 개만 더

`seeds/poi_seed.json` 100건은 속성이 잘 들어와 있다(신뢰도 0.41~0.90). 두 가지만.

- **`quality_score`** — `sentiment_score`만 있고 이 컬럼이 없다. 산출이 A4-4라
  이른 건 맞다. B는 없으면 **중립 0.5**로 두고 임의로 만들지 않는다 —
  `sentiment_score`로 흉내 내면 나중에 A의 실제 공식과 두 값이 어긋난다
- **`hotspot_code`** — 전 건 NULL이라 목 응답에서 실시간 신호 케이스가 통째로
  사라졌다. 목에서는 지점 반경 규칙으로 유도하도록 B가 막아 뒀지만,
  A3-3이 끝나면 실제 코드가 들어온다. **1km 밖 NULL 유지만 지켜 달라**

### 7-4. 부탁 — 공공데이터포털 인증키

`PUBLIC_DATA_API_KEY`를 이미 쓰고 있는데, B의 기상청 단기예보가 **같은 포털의
같은 인증키**다(`apis.data.go.kr/1360000/VilageFcstInfoService_2.0`).
새 승인 없이 **'기상청_단기예보 조회서비스' 활용신청만 추가**하면 된다(자동승인).
B 쪽은 `KMA_SERVICE_KEY`라는 다른 이름으로 읽을 뿐 값은 같다.
이거 하나로 W3의 마지막 미검증 항목이 닫힌다.

---

## 8. 추가 (2026-08-23) — W3 적재분(폴링·핫스팟 매핑)을 읽어 보고

`poll_citydata.py` · `map_poi_hotspot.py` · 리뷰 수집을 B가 실제로 소비하는
쪽에서 확인했다. **A가 고쳐야 할 것은 없다.** 대신 B가 맞춘 것 하나와,
같은 게이트웨이를 쓰는 A에게 그대로 해당되는 것 두 개를 남긴다.

### 8-1. `fcst`는 A의 형태가 맞다 — B가 맞췄다

§2-3에서 B가 "`FCST_PPLTN` 배열을 그대로 넣어달라"고 적었는데, A는 이렇게 넣었다.

```jsonc
{"population": [...FCST_PPLTN...], "weather": [...FCST24HOURS...]}
```

**이쪽이 낫다.** 날씨 예보까지 한 컬럼에 보존되고, 실제로 그 덕을 B가 봤다(§8-2).
`live_signals.fcst_items()`가 배열·객체 둘 다 받도록 고쳤으니 그대로 두면 된다.
§2-3의 예시는 이 문단으로 대체한다.

> 다만 이게 **조용히 비어 있었다**는 점은 기록해 둔다. B가 배열만 훑어서
> `congest_at_visit`이 항상 `null`이었다. 에러가 아니라 배너 한 줄이 사라지는
> 형태여서 양쪽 다 몰랐다. 지금은 실제 응답으로 뜬 픽스처로 계약 테스트를
> 건다 — `roleB/tests/test_citydata_contract.py`. A가 적재 형태를 바꾸면
> **이 테스트가 먼저 깨진다.** 그게 목적이다.

### 8-2. 🟠 4-3(`fcst`)은 닫혔다 · 4-4(`BASELINE_AGE_RATE`)는 열려 있다

- **`fcst` ✅** — 12슬롯이 들어온다. 실측해 보니 2시간이 아니라 **1시간 간격**이다.
  B의 ±90분 매칭에는 더 유리하다.
- **`age_rates`** — `PPLTN_RATE_0`~`_70` 8개가 다 온다. B의 `BASELINE_AGE_RATE`는
  10~60뿐이라 0·70은 점수에 안 쓰고 배너 표기만 처리했다(`10대 미만`/`70대 이상`).
  **§4-4 부탁은 그대로다** — 폴링이 며칠 쌓이면 실측 평균을 알려달라.
  지금 값은 B가 넣은 잠정치고, `live_segment_match`의 분모다.

### 8-3. 🔴 게이트웨이 호출 두 가지 — A의 LLM 배치에 그대로 해당된다

W1 실측(§3-1) 이후 두 가지가 바뀌었다. **A의 속성추출 배치도 같은 게이트웨이를
쓰므로 그대로 막힌다.** 전문은 [`LLM_QUOTA.md` §0](LLM_QUOTA.md).

| # | 증상 | 원인 | 조치 |
|---|---|---|---|
| 1 | `403  error code: 1010` | 앞단 Cloudflare가 기본 UA(`Python-urllib/3.x`)를 차단 | 요청에 **`User-Agent` 헤더를 붙인다** |
| 2 | `404 Model 'gpt-5.4-nano' not found` | 게이트웨이에서 내려갔다 | **`gemini-3.5-flash-lite`** 로 교체 (실측 재측정 완료) |

`requests`/`httpx`를 쓰면 1번은 자동으로 안 걸린다(자기 UA를 붙인다).
A의 `roleA/common/llm.py`가 어느 쪽인지만 확인하면 된다.

> 2번은 §3-1의 소요 계산에 영향이 없다. 새 모델이 nano와 지연이 거의 같다
> (2.4초 vs 2.3초). **T1 800 POI = 직렬 31분 / 동시 8이면 4분**, 그대로다.
> `json_schema` + `strict: true` 강제도 그대로다 — 후보 5종 전부 지켰다.

### 8-4. `hotspot_code` 매핑은 계약대로다 ✅

`map_poi_hotspot.py`가 1km 밖을 `NULL`로 남긴다(`MAX_DISTANCE_M = 1000`).
§2-1의 규칙 그대로다. 이제 B의 실시간 항이 **관측 가능한 상태**가 됐다 —
`hotspot_code`가 있는 POI와 없는 POI가 섞여야 §6.4 재정규화가 실제로 검증된다.

### 8-5. 부탁 — `DATABASE_URL`을 B에게도 (읽기 전용이면 충분하다)

지금 B는 **실 DB를 한 번도 못 봤다.** 위의 확인은 전부 코드와 API 응답을 읽어
한 것이고, 아래는 여전히 대조하지 못했다.

- `roleB/tools/check_data_readiness.py` — "순위를 실제로 움직이는 가중치 몇 %"
- `roleB/tests/test_live_db.py` — 32건이 지금 **skip**이다. DSN만 있으면 돈다

`MOCK_MODE=false` 전환 판단이 이 두 개에 걸려 있다(§7-2). Supabase의
읽기 전용 롤이면 충분하다.

### 8-6. 남은 블로커 (§0 우선순위 갱신)

| 순위 | 항목 | 상태 |
|---|---|---|
| 1 | `poi.commercial_area_id` | ✅ W2에 95.64% — **닫혔다** |
| 2 | `tag_embedding` 16행 | ❌ 아직. 취향 항 0.16이 상수 |
| 3 | `poi.quality_score` | ❌ 아직 (`compute_quality`) |
| 4 | `poi.attr_confidence` | ❌ 전 건 0 — **이게 열리기 전엔 전환 불가**(§7-2) |
| 5 | `review_chunk` 적재 | ⏳ 수집은 돌고 있으나 청크가 DB에 없다 |
| 6 | `hotspot_snapshot` | ✅ 폴링 가동 · `fcst` 채워짐 |

### 8-7. 실 DB 대조 완료 (2026-08-23 저녁) — 숫자로

DSN을 받아 처음으로 실 DB를 봤다. `python -m tools.check_data_readiness` 결과다.

| 항 | 가중치 | 채움 | 판정 |
|---|---|---|---|
| poi 적재 | — | 6,644 | ✅ |
| **attr_confidence ≥ 0.3** | — | **0 / 6,644** | ❌ **전환 차단** |
| segment_affinity 조인 | 0.22 | 6,354 (95.6%) | ✅ |
| purpose_tags | 0.22 | 0 | ❌ A3-2 |
| tag_vector | 0.16 | 0 | ❌ |
| outdoor_exposure | 0.13 | 100 (1.5%) | ⚠️ 시드 100건뿐 |
| quality_score | 0.09 | 0 | ❌ A4-4 |
| hotspot_code | 0.10 | 4,868 (73.3%) | ✅ |
| hotspot_snapshot fcst | 0.08 | 11/11 | ✅ |
| tag_embedding | — | 0 / 16 | ❌ |
| query_vector_cache | — | 0 / 72 | ❌ |
| review_chunk | — | **0행** | ❌ |

**순위를 실제로 움직이는 가중치: 0.40 / 1.00 (40%).**
전환 판정은 ❌다 — 지금 `MOCK_MODE=false`를 내리면 최근접 폴백으로 주저앉는다.
실제로 확인했다: 실 DB로 `/api/recommend`를 치면 **200 · 3건 ·
`low_confidence: true` · `radius_expanded: true`** 가 나온다. 에러가 아니다.

**⚠️ `outdoor_exposure`가 1.5%인 것을 특히 봐 달라.** DDL 기본값이 0.0 =
"완전 실내"다(§2-1). 6,544건이 실내로 취급되고 있어서 **비가 와도 후보가
안 바뀐다** — 차별점 2번이 통째로 죽어 있다. `attr_confidence`와 같은 배치에서
나오는 값이니 순서상 자연스럽지만, 우선순위에서 빠지지 않게 적어 둔다.

### 8-8. 🟠 폴링이 `*/15`로 안 돈다 — 실측 평균 40분

`hotspot_snapshot` 704개 간격(11지점 · 2일)을 재봤다.

| | 값 |
|---|---|
| 평균 간격 | **40분** |
| 최소 | 15분 |
| 최대 | **115분** |
| 40분 초과 | **220 / 704 (31%)** |

워크플로는 `cron: "*/15"`가 맞다. **GitHub Actions 무료 스케줄이 지연·유실되는
것**이 원인으로 보인다(부하가 걸리면 흔하다). 데이터가 틀리는 건 아니고
해상도가 떨어지는 문제다 — 다만 `FCST_PPLTN`이 1시간 간격이라 40분 평균이면
방문 시각 예측의 ±90분 매칭이 아슬해지는 구간이 생긴다.

B 쪽은 stale 임계값을 40분 → **90분**으로 올렸다. 40분으로 두면 정상 가동 중
31%가 stale로 찍혀 경보가 잡음이 된다. 이제 두 번 연속 유실돼야 걸린다.

A가 볼 만한 것 하나 — **한 번 실행에서 여러 번 폴링**하면 스케줄 지연을
많이 흡수한다. 워크플로 한 번에 5분 간격으로 3회 도는 식이다(잡 하나가
15분을 쓴다). 크론 자체를 촘촘히 하는 것보다 확실하다.

### 8-9. 지점 이름·좌표는 정상 ✅

용산 **11개 지점**이 들어와 있다(§2-7에서 "5~7개면 된다"고 했는데 더 넉넉하다).
이태원 좌표로 최근접 조회하면 `이태원 관광특구`가 나온다. `hotspot_latest` 뷰,
`fcst` 12슬롯(인구) + 24슬롯(날씨), `age_rates` 8밴드 전부 정상이다.

실 DB로 배너를 뽑으면 이렇게 나온다 — **이제 전부 진짜 값이다.**

```jsonc
{"weather": "맑음", "feels_like": 35.6, "pm25_grade": 1, "sunset": "19:31",
 "hotspot": "이태원 관광특구", "congest_now": "보통",
 "congest_forecast_at_visit": "약간 붐빔", "age_mix_top": "20대 34%",
 "weather_source": "citydata"}
```
