# 응답 성능 점검 (B6-2)

> **상태: 실 Supabase 재측정 완료 (2026-08-28).** 목표는 ROLE_B §W4 B4-1의 **p95 300ms**다.
> 재측정: `tools/perf_probe.py`(HTTP 지연) · `tools/query_plan.py`(실행 계획) · `tools/scenario_report.py`(파이프라인 지연)
> 2026-08-10 측정(로컬 Docker · 합성 5,000행)은 아래 §부록에 남긴다. **그 숫자는 더 이상 유효하지 않다.**

---

## 결론 세 줄 (2026-08-28)

1. **쿼리는 빠르다. 왕복이 느리다.** 추천 한 건에 **DB 왕복 10회**가 든다.
   지연의 **83~90%가 왕복 시간**이고, 쿼리 실행 자체는 합쳐서 13ms다.
2. **`p95 300ms`는 지금 배치(Render 싱가포르 ↔ Supabase 서울)로는 도달할 수 없다.**
   왕복 10회 × 싱가포르-서울 RTT(70~90ms) ≈ **700~900ms**다. 코드 최적화로는 못 넘는다.
3. **규모 있는 테이블은 전부 인덱스를 탄다.** 실 데이터 6,644행에서 후보 생성이
   `idx_poi_geom`으로 **10.7ms**. 병목은 쿼리가 아니다.

---

## 1. 실측 (2026-08-28 · 실 Supabase · POI 6,644행)

측정 지점: 개발자 로컬(서울) → Supabase(ap-northeast-2, 서울). **RTT 중앙 27ms.**

```
추천 1회  중앙 319ms  ·  DB 호출 10회  ·  왕복만으로 설명되는 몫 266ms (83%)

   38.7ms  후보 생성 (poi + PostGIS)      ← 실행 10.7ms + 왕복
   34.9ms  hotspot_latest
   27.6ms  최근접 지점
   27.4ms  segment_affinity
   26.9ms  recommendation_log INSERT
   26.5ms  query_vector_cache
   26.4ms  review_chunk 인용
   26.2ms  explanation_cache 조회
   25.8ms  user_profile
   25.4ms  admin_dong zone
   ─────────────────────────────────────
   파이썬 계산 36ms
```

**쿼리 실행 시간 (`tools/query_plan.py`, 실 DB)**

| 쿼리 | 실행 | 인덱스 |
|---|---:|---|
| 후보 생성 (poi + PostGIS) | **10.7ms** | `idx_poi_geom` ✅ |
| 인용 검색 (review_chunk) | 0.1ms | `idx_chunk_poi` ✅ |
| 최신 지점 스냅샷 | 2.3ms | — |

1,000행을 넘는 테이블 중 전체 스캔으로 떨어지는 것은 없다.

---

## 2. 그래서 300ms는 되는가 — 안 된다

지연은 사실상 **`왕복 횟수 × RTT`** 다.

| 배치 | RTT | 왕복 10회 | 판정 |
|---|---:|---:|---|
| 로컬(서울) → Supabase(서울) | 27ms | **319ms** | 목표 근접 |
| **Render(싱가포르) → Supabase(서울)** | **70~90ms** | **700~900ms** | ❌ **목표의 2~3배** |
| Render(싱가포르) → Supabase(싱가포르) | 2~5ms | **60~90ms** | ✅ 여유 |

`render.yaml`의 `region: singapore`이고 Supabase 프로젝트는 `ap-northeast-2`(서울)다.
**Render Free가 고를 수 있는 리전 중 서울은 없다** — 싱가포르가 이미 가장 가깝다.
즉 **엔진 쪽 최적화로 넘을 수 있는 차이가 아니다.**

### 선택지 세 개 (팀 결정이 필요하다)

| # | 방법 | 효과 | 비용 |
|---|---|---|---|
| **①** | **Supabase 프로젝트를 싱가포르(`ap-southeast-1`)로 재생성** | 700~900ms → **60~90ms** | 리전은 생성 후 변경 불가 → **새 프로젝트 + A의 전량 재적재**. 발표 일주일 전이면 위험하다 |
| **②** | 왕복을 더 줄인다 (10 → 6) | 700~900 → **420~540ms** | 코드 변경. 목표엔 여전히 못 미친다 |
| **③** | **목표를 재설정한다** — "p95 1초 이내 · 첫 화면까지 로딩 UX" | 0 | 심사에서 설명이 필요하다 |

**B의 권고: ③ + ②의 값싼 부분.** 이유는 세 가지다.

- 이미 C가 콜드스타트·로딩 UX를 만들어 뒀다. 700ms는 **사용자가 느끼기에 나쁘지 않다.**
  Render Free의 콜드스타트(최대 1분)가 훨씬 큰 위험이고, 그건 UptimeRobot으로 막는다.
- ①은 A의 적재를 통째로 다시 시켜야 한다. **지금 남은 작업(임베딩·품질 점수)이 더 급하다.**
- 발표에서 "무료 티어 두 서비스가 다른 대륙에 있어서 왕복이 지배한다"는 **설명 가능한 제약**이다.
  숨기는 것보다 숫자로 보여주는 게 낫다.

### 이미 줄인 것

- `recommendation_log` INSERT의 **존재 확인 SELECT를 스칼라 서브쿼리로 접었다** (11회 → 10회).
  실측 409ms → 319ms. `tests/test_logging.py`가 왕복 1회를 박아 둔다.

### 더 줄일 수 있는 곳 (아직 안 했다)

| 합칠 대상 | 절약 | 주의 |
|---|---|---|
| `user_profile` + `admin_dong zone` | 1회 | 프로필이 없어도 zone은 나와야 한다 (LEFT JOIN) |
| `hotspot_latest` + 최근접 지점 | 1회 | **스냅샷이 없는 지점은 최근접 후보에서 빠진다** — 의미가 달라진다 |
| `explanation_cache` 조회 | 1회 | 캐시 히트 시에만 이득. 지금은 LLM 키가 없어 항상 미스다 |

---

## 3. 아직 못 잰 것

| | 왜 |
|---|---|
| **Render → Supabase 실측** | Render에 `DATABASE_URL`이 아직 없다(`mode: mock`). C가 넣으면 바로 잰다 → `python -m tools.perf_probe --url https://dacos-wheretogo.onrender.com --repeat 1` |
| **LLM 경로 지연** | `LLM_API_KEY`가 로컬에 없다. 지금 전 시나리오가 `explain_mode: template`이라 **LLM·캐시 경로는 한 번도 측정되지 않았다.** 모델 지연 실측치는 `LLM_QUOTA.md §0-3` (채택 모델 2.4~2.8s) |
| **동시 요청** | 직렬로만 쟀다. Render Free 단일 인스턴스에서 데모 중 동시 접속이 몇이나 될지에 따라 다르다 |

---

## 4. 재측정 방법

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"

python -m tools.query_plan          # 실행 계획 — 인덱스를 타는가
python -m tools.scenario_report     # 파이프라인 지연 + 항별 분산
python -m tools.perf_probe --url https://dacos-wheretogo.onrender.com --repeat 1
```

`perf_probe`는 **`/health`를 먼저 재서 전송 구간의 바닥을 보여준다.** 그 숫자가 크면
서버 로직이 아니라 네트워크 문제다 — 지금이 정확히 그 경우다.

---

## 부록 — 2026-08-10 측정 (더 이상 유효하지 않다)

아래는 **로컬 Docker DB + 합성 5,000행** 기준이다. 같은 머신 안이라 왕복이 사실상 0이었고,
그래서 `p95 149ms`가 나왔다. **실 배포 구성과 다르다** — 이 숫자를 근거로 판단하지 말 것.

이 경험 자체가 교훈이다. **재는 환경과 도는 환경이 다르면 측정은 아무것도 보장하지 않는다.**
`LLM_QUOTA.md §0-1`의 사고(프로브는 httpx, 앱은 urllib)와 같은 부류다.

> **상태: 측정 완료 (2026-08-10).** 목표는 ROLE_B §W4 B4-1의 **p95 300ms**다.
> 재측정: `tools/perf_probe.py`(지연) · `tools/query_plan.py`(실행 계획)

---

## 결론 세 줄

1. **p95 149ms.** 목표 300ms의 절반이다. 지금 구조로 규모를 더 키워도 여유가 있다.
2. **규모 있는 테이블은 전부 인덱스를 탄다.** `poi` 5,000행에서 `idx_poi_geom`
   Bitmap Index Scan, 실행 15.7ms. 전체 스캔으로 떨어지는 쿼리가 없다.
3. **가장 느린 시나리오도 248ms다.** 느린 쪽은 전부 지점 반경 밖(`ichon`·`cheongpa`)
   이고, 후보가 얇아 반경을 넓히는 재시도가 한 번 더 도는 경우다. 예상된 동작이다.

---

## 측정 조건

| 항목 | 값 |
|---|---|
| POI | **5,000행** (시드 100 + 합성 4,900. `--scale 5000`) |
| review_chunk | 200 · query_vector_cache 72 · 지점 스냅샷 2 |
| 모드 | `MOCK_MODE=false` (실 PostGIS 3.4.3 + pgvector 0.8.6) |
| LLM | 키 없음 → `explain_mode: template`. **캐시·LLM 경로는 미측정** |
| 서버 | uvicorn 단일 프로세스 · 로컬 Docker DB |
| 부하 | 시나리오 20 × 3회 = 60요청 · 직렬 |

> ⚠️ **Render Free는 이 숫자와 다르다.** 인스턴스가 더 작고 Supabase가 네트워크
> 너머에 있다. 여기 숫자는 "쿼리와 로직이 무겁지 않다"는 것을 보이는 것이고,
> prod 실측은 배포 후 `--url https://dacos-wheretogo.onrender.com`으로 따로 잰다.

---

## 지연 (`tools/perf_probe.py --repeat 3 --no-pace`)

```
전송 바닥(/health): p50=31ms p95=36ms

n=60 min=91 p50=114 p95=149 p99=248 max=248 (ms)
전송 바닥을 뺀 서버 시간: p50≈83ms p95≈112ms
✅ p95 149ms ≤ 300ms
```

### 느린 시나리오 (p95)

| 시나리오 | p95 | 왜 |
|---|---|---|
| S12 가족 5인 주말 점심 (이촌) | 248ms | 5인 수용 + 지점 밖. 후보가 얇아 반경 확대가 돈다 |
| S13 고예산 데이트 (한남) | 206ms | 예산밴드 4라 후보가 많다 — 스코어링 대상이 늘어난다 |
| S10 원효로 작업 (cheongpa) | 152ms | 지점 밖 |

느린 축이 **"후보가 너무 적거나 너무 많은 쪽"** 이라는 게 중요하다. 규모가 커지면
후자가 늘어나므로, 300ms를 넘기 시작하면 §10 판단표대로 **상위 N을 20→12**로
줄이는 것이 먼저다(후보 수 자체는 커버리지라 함부로 못 줄인다).

---

## 실행 계획 (`tools/query_plan.py`)

```
poi 5000행 기준

✅ 후보 생성 (poi + PostGIS): 15.7ms
    idx_poi_geom 사용
    작은 테이블 Seq Scan(정상): user_profile
⚠️ 인용 검색 (review_chunk, 사전필터): 0.1ms
    기대 인덱스 idx_chunk_poi를 쓰지 않았다
    작은 테이블 Seq Scan(정상): review_chunk
✅ 최신 지점 스냅샷: 0.1ms

✅ 1,000행을 넘는 테이블은 전부 인덱스를 탄다
```

`review_chunk`의 ⚠️는 **문제가 아니다.** 200행짜리 테이블에서 플래너가 인덱스를
쓰지 않는 것은 정상이고, 쓸 이유가 없어서다. A가 T1 800 POI × 3청크를 채우면
2,400행이 되고 그때 `idx_chunk_poi`를 타기 시작한다. 그 시점에 다시 재면 된다.

---

## 측정할 때 걸린 함정 두 개

둘 다 **틀린 숫자를 그럴듯하게** 만드는 종류다.

### 1. 레이트 리밋이 429 응답 시간을 재게 한다

분당 10회 제한(B5-6)이 걸린 상태에서 20회를 연달아 쏘면 11번째부터 429가 온다.
429는 DB를 안 보므로 1ms다. 그게 섞이면 **p50이 1ms로 나오고 "빠르다"는 결론**이
나온다. 실제로 한 번 그렇게 쟀다.

→ 측정 시 서버에 `RATE_LIMIT_PER_MIN=0`을 켜고 `--no-pace`, 또는 기본값대로
간격을 벌린다. 도구가 429를 세서 경고한다.

### 2. `localhost`가 IPv6로 먼저 풀리면 요청마다 2초가 붙는다

Windows에서 `localhost` → `::1` 시도 → 실패 → `127.0.0.1` 재시도 경로를 타면
**요청당 약 2초**가 생긴다. 파이프라인은 그대로인데 p95가 2,200ms로 나온다.

```
전송 바닥(/health): p50=2049ms      ← localhost
전송 바닥(/health): p50=31ms        ← 127.0.0.1
전송 바닥을 뺀 서버 시간: 두 경우 모두 p50≈113ms
```

→ `perf_probe`가 매번 `/health`로 **전송 바닥을 먼저 재고** 그만큼을 빼서 보여준다.
바닥이 500ms를 넘으면 경고한다. `--url`에는 `127.0.0.1`을 쓴다.

---

## 재측정 방법

```powershell
cd roleB
$env:MOCK_MODE = "false"
$env:DATABASE_URL = "postgresql://postgres:devpass@localhost:5432/wheretogo"
$env:RATE_LIMIT_PER_MIN = "0"          # 측정 중에만
python -m uvicorn app.main:app --port 8000

# 다른 창에서
python -m tools.perf_probe --url http://127.0.0.1:8000 --repeat 3 --no-pace
python -m tools.query_plan

# prod (레이트 리밋을 끄지 않으므로 간격을 벌린다)
python -m tools.perf_probe --url https://dacos-wheretogo.onrender.com --repeat 1
```

규모를 바꿔가며 보려면 `python -m tools.load_seed_db --scale 20000` 뒤에
`VACUUM ANALYZE poi;`를 잊지 않는다. 통계가 낡으면 플래너가 다른 선택을 한다.

---

## 아직 측정하지 못한 것

| 항목 | 왜 | 언제 |
|---|---|---|
| LLM 경로 지연 | `LLM_API_KEY` 없음 | 키 확보 후 |
| 캐시 히트 지연 | 캐시가 채워지지 않는다(위와 같은 이유) | 〃 |
| Render Free 실측 | prod가 아직 `MOCK_MODE=true` | DB 연결 후 |
| 동시 요청 | 발표 시연은 직렬이라 후순위 | 필요해지면 |

LLM 경로는 게이트웨이 실측(docs/LLM_QUOTA.md)에서 **호출당 2.3초**였다.
설명 생성이 붙으면 첫 요청은 초 단위가 된다 — 그래서 W6 B6-4 캐시 워밍이 있다.
