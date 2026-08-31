# 시나리오 20개 실주행 리포트

> `python -m tools.scenario_report --md` 로 생성. 실 Supabase 대조.
> B6-1(가중치 튜닝 근거) · A6-4(데모 시나리오 데이터 검증)

**결과 반환 20/20**

## 항별 — 실제로 순위를 가르는가

항이 죽는 방식은 에러가 아니다. 입력이 비면 전 POI가 같은 값(중립)이 되고
응답은 200이다. 그래서 **후보 집합 안의 표준편차**를 잰다 — 0이면 기여 0이다.

| | 항 | 가중치 | 표준편차 평균 | 관측 |
|---|---|---:|---:|---|
| ✅ | `segment_affinity` | 0.22 | 0.0966 | 20/20 |
| ✅ | `purpose_match` | 0.22 | 0.0794 | 20/20 |
| ✅ | `taste_similarity` | 0.16 | 0.0326 | 20/20 |
| ✅ | `context_fit` | 0.13 | 0.0188 | 20/20 |
| ✅ | `live_segment_match` | 0.10 | 0.0279 | 16/20 |
| ✅ | `quality` | 0.09 | 0.1224 | 20/20 |
| ✅ | `crowd_fit` | 0.08 | 0.0125 | 16/20 |

**순위를 실제로 가르는 가중치: 1.00 / 1.00**

## 시나리오별

| ID | 설명 | zone | 결과 | 지연 | 설명모드 | 인용 | 플래그 |
|---|---|---|---:|---:|---|---:|---|
| S01 | 비 오는 금요일 저녁 데이트 (이태원) | itaewon | 5 | 186ms | template | 5 | — |
| S02 | 토요일 낮 친구모임 4인 (이태원) | itaewon | 5 | 137ms | template | 5 | — |
| S03 | 평일 저녁 회식 8인 (용산역) | yongsan_stn | 5 | 119ms | template | 5 | — |
| S04 | 평일 오전 혼자 작업 (용산역) | yongsan_stn | 5 | 143ms | cache | 5 | — |
| S05 | 주말 오후 가족 나들이 (이촌) | ichon | 5 | 138ms | template | 5 | `radius_expanded` |
| S06 | 지점 밖 · 혼자 저녁 (서빙고) | ichon | 5 | 143ms | template | 5 | `radius_expanded` |
| S07 | 언덕 동네 데이트 (후암) | huam | 5 | 196ms | template | 5 | — |
| S08 | 해방촌 친구모임 (후암) | huam | 5 | 131ms | template | 5 | — |
| S09 | 청파동 혼밥 (cheongpa) | cheongpa | 5 | 137ms | cache | 5 | — |
| S10 | 원효로 작업 (cheongpa) | cheongpa | 5 | 119ms | template | 5 | — |
| S11 | 대형 회식 12인 (남영) | yongsan_stn | 5 | 135ms | cache | 5 | — |
| S12 | 가족 5인 주말 점심 (이촌) | ichon | 5 | 142ms | template | 5 | `radius_expanded` |
| S13 | 고예산 데이트 (한남) | itaewon | 5 | 150ms | template | 5 | — |
| S14 | 저예산 친구모임 (청파) | cheongpa | 5 | 145ms | cache | 5 | — |
| S15 | 박물관 앞 가족 (용산동) | ichon | 5 | 136ms | cache | 5 | — |
| S16 | 심야 친구모임 (이태원) | itaewon | 5 | 200ms | template | 5 | — |
| S17 | 이른 아침 혼자 (용산역) | yongsan_stn | 5 | 157ms | template | 5 | — |
| S18 | 점심 회식 6인 (한강로) | yongsan_stn | 5 | 135ms | cache | 5 | — |
| S19 | 주말 저녁 데이트 (후암) | huam | 5 | 131ms | template | 5 | — |
| S20 | 평일 낮 작업 (한남) | itaewon | 5 | 144ms | template | 5 | — |

지연은 **파이프라인 내부**만이다(HTTP·직렬화 제외). p50 138 / p95 196 ms.
HTTP 포함 실측은 `tools/perf_probe.py`가 낸다.
