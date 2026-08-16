# 목 API 배포 절차 (B1-4)

> 이 문서의 목적은 하나다. **C가 W1 안에 개발을 시작할 수 있게 하는 것.**
> 코드는 이미 배포 가능한 상태다. 남은 것은 계정 연결 한 번이다.

---

## 0. 무엇이 준비되어 있나

| | |
|---|---|
| 앱 | `roleB/app` — DB 없이 뜬다 (`MOCK_MODE=true`) |
| 블루프린트 | 레포 루트 `render.yaml` — Render가 읽는다 |
| 컨테이너 | `roleB/Dockerfile` — 백업 경로(HF Spaces·로컬 재현)용 |
| 헬스체크 | `GET /health` |

목 응답에는 **`X-Mock-Response: true` 헤더**가 붙는다. 실서버로 바뀌면 사라진다.

---

## 1. 로컬 확인 (2분)

```powershell
cd roleB
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

- 문서: http://localhost:8000/docs
- 헬스: http://localhost:8000/health

```powershell
pytest tests/ -v
```

---

## 2. Render 배포

1. Render 가입 — **결제수단 등록 화면이 나오면 즉시 중단한다** (PLAN.md §0.1).
   그 경우 4번의 백업 경로로 간다.
2. New → **Blueprint** → 이 레포 선택 → `render.yaml`이 자동 인식된다.
3. 생성된 서비스의 Environment에서 `CORS_ORIGINS`에 Vercel 도메인을 추가한다.
   **W1에도 필요하다.** W1 게이트에 "Vercel 배포본에서 API 호출"이 들어 있어서
   `http://localhost:3000`만 넣어두면 게이트에서 막힌다 (ROLE_C_WEB.md §5 배포순서 5).
   ⚠️ 대시보드 값이 `render.yaml`보다 우선한다. 양쪽을 함께 고쳐야 다음 동기화에서 원복되지 않는다.
4. 배포 후 확인:

```bash
curl https://dacos-wheretogo.onrender.com/health
curl -X POST https://dacos-wheretogo.onrender.com/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u_1","purpose":"데이트","party_size":2,"budget_band":3,
       "location":{"lat":37.5340,"lng":126.9946},
       "visit_at":"2026-08-03T19:00:00+09:00"}'
```

5. ~~**prod URL을 C에게 전달**하고 `roleB/openapi.yaml`의 `servers`를 실제 URL로 갱신한다.~~
   → 완료 (2026-08-10). prod는 `https://dacos-wheretogo.onrender.com` 이다.

> 첫 요청은 슬립에서 깨어나느라 최대 1분 걸린다. 이건 고장이 아니다.
> C가 UptimeRobot에 `/health`를 5분 간격으로 등록하면 사라진다.

---

## 3. UptimeRobot (C 담당, W2)

- Monitor Type: HTTP(s) / URL: `https://dacos-wheretogo.onrender.com/health` / Interval: 5분

### ⚠️ 750시간은 생각보다 빡빡하다 (2026-08-07 확인)

무료 한도는 **워크스페이스당 월 750 인스턴스시간**이고, 초과하면 과금이 아니라
**다음 달까지 서비스가 정지**된다. PLAN.md §9.2의 "월 ~720시간"은 30일 기준이다.

```
30일 × 24h = 720h  → 여유 30시간
31일 × 24h = 744h  → 여유  6시간   ← 8월·10월·12월
```

여기서 나오는 규칙 두 가지.

1. **같은 워크스페이스에 무료 서비스를 두 개 만들지 않는다.** 750시간은 서비스별이 아니라
   워크스페이스 합산이다. C가 다른 무료 서비스를 띄우려 하면 반드시 조율한다.
2. **24시간 핑이 꼭 필요한 건 아니다.** UptimeRobot 모니터를 작업·데모 시간대에만 켜두면
   여유가 크게 생긴다. 발표 당일만 상시 가동해도 콜드스타트는 막을 수 있다.

> Render의 **무료 Postgres는 생성 30일 후 만료**된다(14일 유예 후 삭제). DB를 Supabase로
> 잡은 §9.2의 판단이 맞았다 — Render DB를 썼으면 6주차 발표 직전에 사라진다.
> 결제수단은 가입·배포에 **필요 없다**. 한도를 넘겨도 청구가 아니라 정지다 (§0.1 통과).

---

## 4. 백업 경로 — Hugging Face Spaces

Render가 결제수단을 요구하거나 무료 조건이 바뀌면 여기로 옮긴다 (PLAN.md §11.2).

1. New Space → SDK: **Docker**
2. 레포의 `roleB/`를 Space 루트로 올린다 (`Dockerfile`이 이미 있다)
3. Settings → Variables에 `MOCK_MODE`, `CORS_ORIGINS` 추가
4. 슬립 기준이 48시간이라 UptimeRobot 없이도 데모가 버틴다

---

## 5. W2에 바뀌는 것

| 지금 | W2 |
|---|---|
| `MOCK_MODE=true` | `false` + `DATABASE_URL`(Supabase) 주입 |
| 내장 픽스처 14개 | A의 `seeds/poi_seed.json` → 이후 실 POI |
| `/health`의 `db: false` | `SELECT 1` 성공 여부 |

`MOCK_MODE`만 내리면 되도록 코드를 짜 두었다. 엔드포인트 경로와 응답 형태는 바뀌지 않는다.
