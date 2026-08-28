# A(데이터)가 해야 할 것 — 2026-08-28 기준

> 작성 B(추천 엔진) · 받는 사람 A(데이터)
> `origin/main` 기준 · **모든 숫자는 실 Supabase 조회 결과다.**
> 계약 원문은 [`HANDOFF_TO_A.md`](HANDOFF_TO_A.md), 전체 상황은 [`BRIEF_2026-08-28.md`](BRIEF_2026-08-28.md).

---

## 먼저 — 지금 어디까지 왔나

**A가 넣은 것 덕분에 파이프라인이 처음으로 끝까지 이어졌다.**

```
poi 6,644건 · zone 100% · 상권 95.6% · 핫스팟 매핑 73.3%
T1 800건 LLM 속성 추출 완주 (attr_confidence >= 0.5 가 77.0%)
review_chunk 2,200청크 / 761 POI
segment_affinity 44,064행   ← 이게 이번 주 최대 진전
```

`segment_affinity`가 들어오면서 **순위를 실제로 가르는 가중치가 0.43 → 0.75 / 1.00**이 됐다
(측정: `python -m tools.scenario_report`). 시나리오 20개가 **전부** 결과를 반환한다(A6-4 통과).

**남은 0.25는 전부 아래 A-2 · A-3 두 개다.** 그것만 들어오면 1.00이다.

---

> ### 🔎 LLM 심사자가 실제로 지적한 것 (2026-08-28 · `docs/LLM_JUDGE_REPORT.md`)
>
> 시나리오 20개를 LLM에 채점시켰다(B6-3). **지적 내용이 아래 미완 항목과 정확히 겹친다** —
> 추측이 아니라 심사자 관점에서 실제로 감점 요인으로 잡힌 것들이다.
>
> | 지적 | 대응 항목 |
> |---|---|
> | *"테니스 레슨장이 1인 작업 목적에 전혀 맞지 않는다"* (S10) | **A-7** 추천 대상 아닌 업종이 후보에 남아 있다 |
> | *"점심 장사 위주인데 20시 모임에 추천됐다"* (S08) | **A-5** `business_hours` 0건 → `is_open_at()`이 항상 TRUE |
> | *"픽업만 가능한 곳을 가족 나들이에"* (S05) | T2·T3 속성 미확보 |
> | *"애견카페가 4인 친구모임 목적에 안 맞는다"* (S02) | 위와 같음 |
>
> 축별 점수에서 가장 낮은 것은 `context_fit` **2.55 / 5**다.
> **가중치 문제가 아니라 데이터 문제다** — `outdoor_exposure` 실제 관측이 2.1%뿐이라
> 날씨가 순위를 못 바꾼다. 이게 이 서비스의 차별점 2번이다.

## 우선순위 요약

| 순 | 항목 | 없으면 | 예상 |
|---|---|---|---|
| 🔴 **1** | [A-1 폴링 복구](#a-1-폴링이-사실상-멈췄다) | 실시간 축 0.18이 "실시간"이 아니다 | 20분 |
| 🔴 **2** | [A-2 `tag_embedding` 16행](#a-2-tag_embedding-16행--투입-대비-효과-최대) | 취향 축 0.16이 상수 | 30분 |
| 🔴 **3** | [A-3 `embed_chunks.py`](#a-3-embed_chunkspy--임베딩-배치-a4-2) | 위와 같음 + RAG 벡터 정렬 불가 | 2시간 |
| 🟠 **4** | [A-4 `compute_quality.py`](#a-4-compute_qualitypy--품질-점수-a4-4) | 품질 축 0.09가 상수 | 1시간 |
| 🟠 **5** | [A-5 `business_hours`](#a-5-business_hours--데모-사고-방지) | **닫힌 가게가 1등으로 나올 수 있다** | 1~2시간 |
| 🟡 **6** | [A-6 `build_affinity.py` 커밋](#a-6-build_affinitypy가-레포에-없다) | 재현·검증·발표 설명이 막힌다 | 30분 |
| 🟡 **7** | [A-7 업종 매핑 7종](#a-7-segment_affinity에-없는-업종-7종) | POI 450건이 개인화에서 빠진다 | 1시간 |
| 🟡 **8** | [A-8 `query_vector_cache` 72행](#a-8-query_vector_cache-72행) | 인용이 최신순 폴백 | 30분 (A-3 뒤) |
| ⚪ **9** | [A-9 `common/*.py` 3개가 0 bytes](#a-9-commonpy-3개가-0-bytes다) | 배치 재현 불가 | 1시간 |
| ⚪ **10** | [A-10 커버리지 리포트](#a-10-커버리지품질-리포트-a5-4--a6-1) | 발표 자료 수치 | 1시간 |

**검증은 언제나 이 한 줄이다.**

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"
python -m tools.check_data_readiness
```

마지막 줄 **"순위를 실제로 움직이는 가중치"** 가 지금 몇인지 알려준다. 작업 전후로 돌려서 올라갔는지 보면 된다.

---

## A-1. 폴링이 사실상 멈췄다

### 무엇이 문제인가

```
hotspot_snapshot        1,814행
최신 스냅샷             2026-08-27 23:30 UTC  (6시간 전)
최근 30시간 실행 횟수    2회      ← *​/15 크론이면 120회여야 한다
```

GitHub Actions 실행 이력에도 `Poll Seoul Citydata`가 하루 1~2회밖에 안 보이고 `cancelled`도 섞여 있다.

### 왜 중요한가

`live_segment_match`(0.10) + `crowd_fit`(0.08) = **0.18**이 과거 값으로 계산된다.
엔진은 90분 넘은 스냅샷에 경고 로그를 띄우지만 **결과는 그대로 200으로 나간다.**
배너의 *"지금 보통 → 22시 여유"* 가 어제 값이라는 뜻이고, 이건 이 서비스의 차별점 1번이다.

### 어떻게 고치나

**GitHub Actions 무료 스케줄은 `*/15`를 지켜주지 않는다.** 부하가 걸리면 건너뛰고, 그 사실을 알려주지도 않는다.
**잡 하나가 15분을 쓰면서 그 안에서 5분 간격으로 3번 도는 방식**이 훨씬 확실하다.

```yaml
# .github/workflows/poll-citydata.yml
on:
  schedule:
    - cron: "*/15 * * * *"      # 실제로는 1시간에 1~2번만 뜬다고 가정한다
  workflow_dispatch:

concurrency:
  group: poll-seoul-citydata
  cancel-in-progress: false      # 지금 값 그대로. 취소되면 그 회차를 통째로 잃는다

jobs:
  poll-citydata:
    runs-on: ubuntu-latest
    timeout-minutes: 20          # 10 -> 20. 아래 루프가 15분을 쓴다
    steps:
      # ... checkout / setup-python / pip install 은 그대로 ...

      - name: Poll Seoul citydata (5분 간격 3회)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SEOUL_API_KEY: ${{ secrets.SEOUL_API_KEY }}
        run: |
          for i in 1 2 3; do
            echo "--- pass $i ---"
            python -m roleA.jobs.poll_citydata || echo "pass $i 실패 — 계속한다"
            [ $i -lt 3 ] && sleep 300
          done
```

`|| echo`를 붙이는 이유 — 3회 중 1회가 실패해도 나머지 2회는 돌아야 한다.
지금은 한 번 실패하면 잡이 통째로 죽고 그 15분이 비어 버린다.

### 완료 기준

```powershell
cd roleB; python -m tools.check_data_readiness
#   "최근 스냅샷 N분 전" 이 90분 이내
```

```sql
-- 최근 6시간에 최소 12회 이상 찍혀야 한다
SELECT count(DISTINCT observed_at) FROM hotspot_snapshot
WHERE observed_at > now() - interval '6 hours';
```

---

## A-2. `tag_embedding` 16행 — 투입 대비 효과 최대

### 무엇이 문제인가

```
tag_embedding    0 / 16행
poi.tag_vector   0 / 6,644
```

이 둘이 없으면 온보딩이 `user_profile.taste_vector`를 만들지 못한다(NULL이 된다).
그러면 `taste_similarity` **0.16이 전 POI에서 같은 값(0.5)** 이 되고 순위에 아무 기여를 못 한다.

### 왜 A-3보다 먼저인가

**임베딩을 16번만 하면 끝나기 때문이다.** 분위기 10종 + 목적 6종.
`poi.tag_vector`(6,644건)는 A-3에서 하더라도, 이 16행은 지금 30분이면 넣을 수 있다.

> 다만 **둘 다 있어야 코사인이 의미를 갖는다.** `tag_embedding`만 넣으면 사용자 벡터는 생기지만
> 비교 대상(`poi.tag_vector`)이 없어서 여전히 중립이다. 그래도 먼저 넣어 두는 게 좋다 —
> A-3에서 같은 모델로 이어서 돌리면 되고, 온보딩 경로가 살아 있는지 먼저 확인할 수 있다.

### 어떻게 하나

**어휘는 반드시 `roleB/app/constants.py`에서 가져온다.** 손으로 적으면 한 글자가 틀리고,
그러면 조회가 0행이 되는데 **에러가 아니라 조용히 빠진다.**

```python
# Colab 또는 로컬 GPU
from sentence_transformers import SentenceTransformer
import psycopg

ATMOSPHERE = ["조용한","활기찬","감성적인","트렌디한","로컬한",
              "넓은","뷰가좋은","아늑한","이국적인","가성비"]      # constants.ATMOSPHERE_TAGS
PURPOSE    = ["데이트","친구모임","혼자","가족","작업","회식"]      # constants.PURPOSE_TAGS

model = SentenceTransformer("BAAI/bge-m3")
rows = [(t, "atmosphere") for t in ATMOSPHERE] + [(t, "purpose") for t in PURPOSE]
vecs = model.encode([t for t, _ in rows], normalize_embeddings=True)   # 1024차원

with psycopg.connect(DSN) as conn, conn.cursor() as cur:
    for (tag, kind), v in zip(rows, vecs):
        cur.execute(
            "INSERT INTO tag_embedding (tag, kind, embedding) VALUES (%s, %s, %s) "
            "ON CONFLICT (tag) DO UPDATE SET embedding = EXCLUDED.embedding",
            (tag, kind, "[" + ",".join(f"{x:.6f}" for x in v) + "]"),
        )
    conn.commit()
```

- 컬럼 타입은 `HALFVEC(1024)`다. **문자열 `"[0.1,0.2,...]"` 형태로 넣으면 pgvector가 캐스팅한다.**
- `normalize_embeddings=True` — 코사인을 쓸 거라 정규화해 두는 편이 안전하다.
  **단, A-3의 `poi.tag_vector`·`review_chunk.embedding`도 같은 설정이어야 한다.**

### 완료 기준

```sql
SELECT kind, count(*) FROM tag_embedding GROUP BY kind;
--   atmosphere 10 / purpose 6

-- 어휘가 계약과 정확히 같은가 (0행이어야 정상)
SELECT tag FROM tag_embedding
EXCEPT SELECT unnest(ARRAY['조용한','활기찬','감성적인','트렌디한','로컬한',
  '넓은','뷰가좋은','아늑한','이국적인','가성비',
  '데이트','친구모임','혼자','가족','작업','회식']);
```

---

## A-3. `embed_chunks.py` — 임베딩 배치 (A4-2)

### 무엇이 문제인가

```
poi.tag_vector            0 / 6,644
review_chunk.embedding    0 / 2,200
```

`taste_similarity`(0.16)가 통째로 상수이고, RAG가 **벡터 정렬 없이 최신순 폴백**으로 돌고 있다.
인용이 나오긴 하지만 "질문과 가까운 문장"이 아니라 "최근 문장"이다.

### 어떻게 하나

**모델을 서버에 올리지 않는다.** bge-m3는 약 2GB고 Render Free 메모리에 안 들어간다.
Colab 무료 GPU나 본인 PC에서 돌리고 **결과 벡터만 적재**한다 (`ROLE_A_DATA §A4-2`).

**두 가지를 채운다.**

```python
# ① poi.tag_vector = mean(embed(atmosphere_tags + purpose_tags))
#    태그가 없는 POI(purpose_tags IS NULL)는 건너뛴다. 0벡터를 넣지 말 것 —
#    엔진은 NULL을 "취향 축 관측 불가 = 중립"으로 읽는다. 0벡터는 "정반대"가 된다.

SELECT poi_id, atmosphere_tags, purpose_tags FROM poi
WHERE (atmosphere_tags IS NOT NULL AND cardinality(atmosphere_tags) > 0)
   OR (purpose_tags    IS NOT NULL AND cardinality(purpose_tags)    > 0);
# -> 약 768건 (T1 추출분)

# ② review_chunk.embedding = embed(text)
SELECT chunk_id, text FROM review_chunk WHERE embedding IS NULL;
# -> 2,200건
```

```python
UPDATE_POI = "UPDATE poi SET tag_vector = %s WHERE poi_id = %s"
UPDATE_CHK = "UPDATE review_chunk SET embedding = %s WHERE chunk_id = %s"
# 값은 "[0.1,0.2,...]" 문자열. 1024차원. A-2와 같은 모델·같은 normalize 설정.
```

### 반드시 지킬 것 세 가지

1. **`tag_embedding`(A-2)과 같은 모델·같은 공간이어야 한다.** 다른 모델로 만들면 코사인이
   숫자는 나오는데 의미가 없다 — 에러가 안 나서 제일 위험하다.
2. **차원은 1024다.** 다르면 INSERT에서 터진다(그건 다행이다).
3. **체크포인트를 넣는다.** 2,200건이면 중간에 끊길 수 있다. `WHERE embedding IS NULL`로
   다시 돌리면 이어지도록 짜면 된다.

### 완료 기준

```sql
SELECT count(*) FROM poi WHERE tag_vector IS NOT NULL;          -- 700+
SELECT count(*) FROM review_chunk WHERE embedding IS NOT NULL;  -- 2,200
```

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"
python -m tools.scenario_report
#   taste_similarity 가 DEAD -> OK 로 바뀌어야 한다
#   "순위를 실제로 가르는 가중치" 0.75 -> 0.91
```

---

## A-4. `compute_quality.py` — 품질 점수 (A4-4)

### 무엇이 문제인가

```
poi.quality_score     0 / 6,644
poi.sentiment_score   749건 있음      ← 재료는 이미 다 있다
poi.mention_count     800건 (T1 전량)
```

계산만 안 돌았다. `quality` **0.09가 상수**다.

### 공식 (`ROLE_A_DATA §A4-4`)

```python
# 베이지안 평균 — 청크가 적은 POI가 극단값으로 튀는 것을 막는다
s_bayes = (C * m + sentiment_score * n_clean) / (C + n_clean)
#   C = 8                          사전 강도
#   m = 전체 POI 평균 sentiment_score
#   n_clean = is_sponsored=false 인 청크 수

quality_score = s_bayes * (log1p(mention_count) / log1p(MENTION_P95))
#   MENTION_P95 = 전체 mention_count 의 95퍼센타일 (상한 클리핑)
```

### SQL 한 방으로도 된다

```sql
WITH stats AS (
    SELECT avg(sentiment_score)                                        AS m,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY mention_count) AS p95
    FROM poi WHERE sentiment_score IS NOT NULL
),
clean AS (
    SELECT poi_id, count(*) AS n_clean
    FROM review_chunk WHERE is_sponsored = FALSE
    GROUP BY poi_id
)
UPDATE poi p
SET quality_score = LEAST(1.0,
      ((8 * s.m + p.sentiment_score * COALESCE(c.n_clean, 0)) / (8 + COALESCE(c.n_clean, 0)))
      * (ln(1 + p.mention_count) / NULLIF(ln(1 + s.p95), 0))
    )
FROM stats s LEFT JOIN clean c ON TRUE
WHERE c.poi_id = p.poi_id AND p.sentiment_score IS NOT NULL;
```

> **`sentiment_score`가 NULL인 POI는 건드리지 않는다.** `quality_score`를 NULL로 두면
> 엔진이 중립(0.5)으로 읽는다. 0을 넣으면 "품질 최악"이 되어 후보에서 밀려난다 —
> 모르는 것과 나쁜 것은 다르다 (`ROLE_B §1.3`).

### 완료 기준

```sql
SELECT count(*) FILTER (WHERE quality_score IS NOT NULL) AS filled,
       min(quality_score), max(quality_score), avg(quality_score)
FROM poi;
-- filled >= 700 · 값이 0~1 안에 있고 전부 같은 값이 아닐 것
```

`python -m tools.scenario_report` 에서 `quality` 가 DEAD → OK.

---

## A-5. `business_hours` — 데모 사고 방지

### 무엇이 문제인가

```
poi.business_hours    0 / 6,644
```

엔진의 `is_open_at()`은 **영업시간을 모르면 TRUE를 반환한다.** 정보가 없다는 이유로 후보에서
떨어뜨리면 커버리지가 무너지기 때문인데, 지금은 **전 건이 "모름"이라 하드필터가 사실상 없다.**

**데모 중에 "지금 닫힌 집"이 1등으로 나올 수 있다.** 심사위원이 제일 먼저 알아채는 종류다.

### 형식

```json
{"mon": ["10:00", "22:00"], "tue": ["10:00", "22:00"], ...}
```

- 요일 키는 `sun mon tue wed thu fri sat` (소문자 3글자)
- 자정을 넘기는 영업(`["18:00","02:00"]`)도 엔진이 처리한다
- **모르는 요일은 키를 빼면 된다.** 그 요일은 TRUE로 처리된다
- 휴무일을 `["00:00","00:00"]`로 넣지 말 것 — 그건 24시간 영업으로 읽힌다. 키를 빼거나 별도 처리

### 어디서 가져오나

우선순위 순으로:

1. **상가정보 CSV에 영업시간 컬럼이 있으면 그걸 쓴다** (있는지부터 확인)
2. **T1 800건만이라도 채운다.** 데모·발표 시나리오는 전부 T1 안에서 구성한다(`PLAN §639`).
   전체를 채울 필요가 없다
3. **업종 기본값으로 채운다** — 카페 08~22, 음식점 11~22, 술집 17~02, 문화시설 10~18.
   근사값이라도 "24시간 영업"보다 훨씬 낫다. 근사값임을 리포트에 남긴다

### 완료 기준

```sql
SELECT count(*) FILTER (WHERE business_hours IS NOT NULL) FROM poi WHERE tier = 1;
-- 최소 600 이상

-- 엔진 함수로 직접 확인
SELECT name, is_open_at(business_hours, now()) FROM poi
WHERE tier = 1 AND business_hours IS NOT NULL LIMIT 10;
```

---

## A-6. `build_affinity.py`가 레포에 없다

`segment_affinity`에 **44,064행이 들어 있는데 그걸 만든 스크립트가 커밋되지 않았다.**
`roleA/jobs/`에 파일이 없다.

이게 왜 문제인가:

- **재적재가 안 된다.** 축이 바뀌거나 원본이 갱신되면 처음부터 다시 해야 한다
- **검증이 안 된다.** 어떤 정규화를 썼는지 코드로 확인할 방법이 없다
- **발표에서 설명할 근거가 없다.** "상권분석 매출을 세그먼트 비중으로 정규화했다"를
  뒷받침하는 게 데이터뿐이다

집계 SQL 초안은 [`HANDOFF_TO_A.md §2-2-1`](HANDOFF_TO_A.md)에 있다. 실제로 돌린 코드가 그와
다르다면 **돌린 쪽을 커밋**하고 문서를 맞춰 달라.

### 완료 기준

`roleA/jobs/build_affinity.py`가 커밋되어 있고, 빈 테이블에서 다시 돌렸을 때 같은 행수가 나온다.

---

## A-7. `segment_affinity`에 없는 업종 7종

```
poi 의 distinct category_l2         19종
segment_affinity 의 distinct        12종
segment 조인되는 POI                5,177 / 6,644 (77.9%)
```

빠진 업종과 POI 수:

| 업종 | POI |
|---|---:|
| 의약품 소매 | 233 |
| 기타외국식 | 111 |
| 서양식 | 47 |
| 기타주점업 | 29 |
| 분식류 | 19 |
| 문화시설 | 10 |
| 기타 관광 | 1 |

**둘 중 하나를 골라야 한다.**

1. **추천 대상 업종이면** 상권분석 원본의 업종코드와 매핑을 채운다.
   `기타외국식`·`서양식`·`기타주점업`은 명백히 추천 대상이다 (187건).
2. **추천 대상이 아니면 `poi`에서 빼거나 tier를 낮춘다.**
   `의약품 소매` 233건은 애초에 "어디 갈까"의 답이 아니다. **후보에 남아 있으면
   비 오는 날 실내 점수를 잘 받아 상위로 올라올 수 있다.**

`문화시설`·`기타 관광`(11건)은 TourAPI 병합분이라 상권분석에 없는 게 정상이다.
이건 `segment_affinity` 항이 중립으로 가는 게 맞다 — 그대로 둔다.

### 완료 기준

```sql
-- 추천 대상인데 조인이 안 되는 업종이 남아 있는가
SELECT p.category_l2, count(*) FROM poi p
WHERE p.category_l2 NOT IN (SELECT DISTINCT category_l2 FROM segment_affinity)
GROUP BY 1 ORDER BY 2 DESC;
```

---

## A-8. `query_vector_cache` 72행

```
query_vector_cache   0 / 72행
```

목적 6 × 날씨상태 4 × 인원밴드 3 = 72. **A-3이 끝난 뒤에** 같은 모델로 이어서 돌리면 된다.

```python
PURPOSES       = ["데이트","친구모임","혼자","가족","작업","회식"]
WEATHER_STATES = ["맑음","비","미세먼지나쁨","폭염한파"]
PARTY_BANDS    = [1, 2, 3]      # 1~2명 / 3~4명 / 5명 이상
PARTY_LABEL    = {1: "1~2명", 2: "3~4명", 3: "5명 이상"}

# 쿼리 문장 예: "3~4명이서 데이트하기 좋은 곳, 비 오는 날"
query_text = f"{PARTY_LABEL[band]}이서 {purpose}하기 좋은 곳, {weather}"
# INSERT INTO query_vector_cache (purpose, weather_state, party_band, query_text, embedding)
```

**없어도 인용은 나간다**(최신순 폴백). 정확도만 떨어진다. 그래서 A-3보다 뒤다.

### 완료 기준

```sql
SELECT count(*) FROM query_vector_cache;   -- 72
```

---

## A-9. `common/*.py` 3개가 0 bytes다

```
roleA/common/config.py    0 bytes
roleA/common/http.py      0 bytes
roleA/common/llm.py       0 bytes
```

`extract_attributes.py`는 실제로 돌았으니(T1 800건 완주) 어딘가 다른 경로가 있다.
**그 코드가 레포에 없으면 아무도 다시 돌릴 수 없다.**

LLM 호출에서 반드시 넣어야 하는 두 가지는 이미 겪었다:

| # | 증상 | 원인 | 조치 |
|---|---|---|---|
| 1 | `403 error code: 1010` | 앞단 Cloudflare가 기본 UA(`Python-urllib/3.x`)를 차단 | **`User-Agent` 헤더** 아무 문자열 |
| 2 | `404 Model not found` | `gpt-5.4-nano`가 내려갔다 | **`gemini-3.5-flash-lite`** |

둘 다 **에러로 안 보이고 조용히 실패**한다. `requests`/`httpx`를 쓰면 1번은 자동으로 안 걸린다.

---

## A-10. 커버리지·품질 리포트 (A5-4 · A6-1)

`roleA/reports/`가 비어 있다. 발표 자료에 들어갈 수치다.

필요한 것:

- POI 수 · tier 분포 · zone별 분포
- `attr_confidence` 분포 히스토그램 (T1 800건)
- 리뷰 수집률 · 청크 수 · 협찬 비율
- `segment_affinity` 커버리지 (상권 52/57 · 업종)
- 데이터 파이프라인 다이어그램 (A6-2)

`roleB/tools/check_data_readiness.py` 출력을 그대로 붙여도 절반은 된다.

---

## 부록 — 자주 쓰는 확인 쿼리

```sql
-- 전체 채움 현황
SELECT count(*) total,
       count(zone) zone, count(commercial_area_id) area, count(hotspot_code) hotspot,
       count(business_hours) hours, count(tag_vector) tagvec, count(quality_score) qual,
       count(*) FILTER (WHERE attr_extracted_at IS NOT NULL) extracted
FROM poi;

-- 고정 어휘가 새지 않았나 (0행이어야 정상)
SELECT DISTINCT unnest(purpose_tags) FROM poi
EXCEPT SELECT unnest(ARRAY['데이트','친구모임','혼자','가족','작업','회식']);

-- 폴링이 살아 있나
SELECT hotspot_code, observed_at, now() - observed_at AS age,
       jsonb_array_length(fcst -> 'population') AS fcst_slots
FROM hotspot_latest;

-- 세그먼트 축이 규약대로인가 (셋 다 0행이어야 정상)
SELECT DISTINCT age_band FROM segment_affinity
EXCEPT SELECT unnest(ARRAY[10,20,30,40,50,60]);
SELECT DISTINCT hour_band FROM segment_affinity WHERE hour_band NOT BETWEEN 0 AND 5;
SELECT DISTINCT gender FROM segment_affinity WHERE gender NOT IN ('M','F');
```

```powershell
# 입력 쪽 점검 — 테이블·컬럼이 채워졌나
cd roleB; $env:DATABASE_URL = "<DSN>"; python -m tools.check_data_readiness

# 출력 쪽 점검 — 실제로 순위가 갈리나 (시나리오 20개 실주행)
cd roleB; $env:DATABASE_URL = "<DSN>"; python -m tools.scenario_report
```

**두 도구가 서로 다른 질문에 답한다.** 앞쪽은 전체 POI 기준 채움률, 뒤쪽은 실제 후보 안의
점수 분산이다. 둘이 크게 어긋나면 배선이 끊긴 것이니 B에게 알려 달라 — 실제로 그런 적이 있다
(`segment_affinity`가 44,064행인데 점수는 전부 중립이었다).
