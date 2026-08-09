# 응답 성능 점검 (B6-2)

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
