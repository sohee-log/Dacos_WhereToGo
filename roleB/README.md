# roleB — 추천 엔진 · 백엔드

담당 문서: [docs/ROLE_B_ENGINE.md](../docs/ROLE_B_ENGINE.md)

후보 생성 · 스코어링 · RAG · API를 담당한다. Render 배포 루트가 이 폴더다.

## 구조

```
roleB/
├── app/
│   ├── main.py              # FastAPI 앱, CORS, 레이트리밋
│   ├── config.py
│   ├── db.py                # 커넥션 풀
│   ├── schemas.py           # Pydantic — C와의 계약
│   ├── constants.py         # 가중치, 고정 어휘, ZONE_BARRIER
│   ├── routers/
│   │   ├── onboarding.py
│   │   ├── context.py
│   │   ├── recommend.py
│   │   ├── feedback.py
│   │   └── poi.py
│   └── services/
│       ├── retrieval.py     # ① 후보 생성 (PostGIS + 하드필터)
│       ├── scoring.py       # ② 스코어링 + 재정규화
│       ├── context_fit.py   # 날씨 비선형 로직
│       ├── live_signals.py  # citydata 기반 실시간 항
│       ├── rag.py           # ③ pgvector 검색
│       ├── explain.py       # LLM 설명 + 캐시 + 템플릿 폴백
│       └── logging_svc.py   # ④ recommendation_log
├── tests/
├── openapi.yaml             # C와의 계약. 변경은 PR
└── requirements.txt
```

## 실행

```bash
cd roleB
uvicorn app.main:app --reload --port 8000
pytest tests/ -v
```

## 다른 폴더와의 관계

| | |
|---|---|
| `../db/` | 스키마. **초안 작성은 내가 하되** 변경은 PR + 3인 리뷰 |
| `../seeds/` | A가 채운다. 개발 중에는 이걸로 돌린다 |
| `../roleC/` | `openapi.yaml`로만 소통한다 |
| `../roleA/` | 건드리지 않는다 |

## 잊지 말 것

- `hotspot_code`가 NULL이면 `live_*` 항은 **None** — 0이 아니다. 가중치를 재정규화한다
- `context_fit`은 **비선형**이다. 기온은 U자형, 미세먼지는 임계값
- 거리에 직선거리만 쓰지 않는다. `ZONE_BARRIER` 10개 조합을 전부 채운다
- pgvector는 **사전 필터** 후 검색한다. 사후 필터는 정확도가 붕괴한다
- 쿼리 벡터는 `query_vector_cache`에서 **조회**한다. 온라인에서 임베딩하지 않는다
- LLM 호출 전 `explanation_cache`를 먼저 본다. 쿼터가 떨어지면 템플릿으로 폴백한다
- `recommendation_log`에 **노출됐지만 선택 안 된 후보**도 남긴다
