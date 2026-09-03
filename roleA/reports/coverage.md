# Role A 데이터 커버리지·품질 리포트

> 기준: W4 완료 + W5 진행 결과  
> 대상 프로젝트: Dacos_WhereToGo  
> 담당: A (데이터)

## 1. 요약

현재 데이터 파이프라인은 POI 적재 → T1 리뷰 수집 → LLM 속성 추출 → 임베딩 → 세그먼트 친화도 → 품질 점수 → 추천 엔진 입력까지 연결된 상태다.

Role B의 `scenario_report` 기준 20개 시나리오가 모두 결과를 반환했고, 추천 점수의 7개 항목이 모두 후보 간 차이를 만들어 **순위를 실제로 가르는 가중치 1.00 / 1.00**을 달성했다.

| 항목 | 결과 |
|---|---:|
| 전체 POI | 6,644 |
| T1 POI | 800 |
| zone 매핑 | 6,644 / 6,644 (100%) |
| 상권 매핑 | 6,354 / 6,644 (95.6%) |
| hotspot 매핑 | 4,868 / 6,644 (73.3%) |
| T1 속성 추출 | 800 / 800 (100%) |
| T1 attr_confidence >= 0.5 | 616 / 800 (77.0%) |
| T1 attr_confidence >= 0.3 | 650 / 800 (81.2%) |
| review_chunk | 2,200 / 761 POI |
| review_chunk embedding | 2,200 / 2,200 |
| tag_embedding | 16 / 16 |
| T1 tag_vector | 738 / 800 |
| segment_affinity | 44,064행 |
| quality_score | 650 / 800 T1 |
| query_vector_cache | 72 / 72 |

---

## 2. POI 기본 데이터

- 전체 POI: **6,644건**
- zone: **100%**
- commercial_area_id: **6,354건 (95.6%)**
- hotspot_code: **4,868건 (73.3%)**

hotspot_code는 핫스팟 중심점에서 1 km 이내인 POI에만 부여하며, 1 km를 넘는 POI는 임의 매핑하지 않고 NULL로 유지한다.

---

## 3. T1 리뷰 수집 및 속성 추출

### 리뷰 후보

W3와 W4 네이버 블로그 검색 결과를 병합하고 URL 중복을 제거한 뒤 POI당 최대 15건을 사용했다.

| 리뷰 후보 수 | POI 수 | 비율 |
|---|---:|---:|
| 1건 이상 | 784 | 98.0% |
| 3건 이상 | 748 | 93.5% |
| 5건 이상 | 689 | 86.1% |
| 8건 이상 | 612 | 76.5% |
| 10건 이상 | 573 | 71.6% |
| 15건 | 458 | 57.3% |
| 0건 | 16 | 2.0% |

### LLM 속성 추출

- 추출 완료: **800 / 800**
- attr_confidence >= 0.5: **616 / 800 (77.0%)**
- attr_confidence >= 0.3: **650 / 800 (81.2%)**
- 평균 attr_confidence: **0.657**
- 중앙값: **0.760**
- attr_confidence = 0: **101건**

### 속성별 관측률

| 속성 | 관측 수 | T1 비율 |
|---|---:|---:|
| outdoor_exposure | 139 | 17.4% |
| purpose_tags | 694 | 86.8% |
| atmosphere_tags | 732 | 91.5% |
| noise_level | 573 | 71.6% |
| price_band | 352 | 44.0% |
| group_capacity | 101 | 12.6% |
| sentiment_score | 749 | 93.6% |
| wait_intensity | 382 | 47.8% |
| business_hours | 0 | 0.0% |

리뷰에서 근거를 찾지 못한 속성은 임의 추정하지 않고 NULL로 유지한다.

---

## 4. 리뷰 청크 및 임베딩

### review_chunk

- review_chunk: **2,200건**
- review_chunk가 존재하는 T1 POI: **761 / 800**
- embedding 완료: **2,200 / 2,200**

리뷰 청크는 네이버 검색 API의 원문 발췌를 사용하며, 모델이 새 문장을 생성해 저장하지 않는다.

### 임베딩 모델

- 모델: **BAAI/bge-m3**
- 차원: **1024**
- normalize_embeddings: **True**
- DB 타입: **HALFVEC(1024)**

### 태그 임베딩

- `tag_embedding`: **16 / 16**
  - 목적 태그 6종
  - 분위기 태그 10종
- `poi.tag_vector`: **738 / 800 T1**

purpose_tags와 atmosphere_tags가 모두 없는 POI는 0벡터를 넣지 않고 NULL로 유지한다.

---

## 5. segment_affinity

### 결과

- 전체 행: **44,064**
- affinity 생성 상권: **52개**
- category_l2: **12종**
- affinity 범위: **0.000 ~ 0.404959**
- 상권 매핑 POI 기준 커버리지: **5,177 / 6,354 (81.48%)**
- 전체 POI 기준 조인 가능 비율: **5,177 / 6,644 (77.9%)**

### 세그먼트 축

- gender: `M`, `F`
- age_band: `10, 20, 30, 40, 50, 60`
- dow_type: `0=평일`, `1=주말`
- hour_band:
  - 0 = 00~06
  - 1 = 06~11
  - 2 = 11~14
  - 3 = 14~17
  - 4 = 17~21
  - 5 = 21~24

### 생성 방식

서울시 2025 상권분석 추정매출 원본은 성별×연령×요일×시간의 결합통계를 제공하지 않는다. 따라서 각 주변분포를 이용해 다음 독립근사를 적용했다.

`estimated_segment_share = gender_share × age_share × dow_share × hour_share`

각 상권×업종 그룹의 affinity 합은 1이 되도록 구성되며, 원본에 존재하지 않는 상권이나 의미가 명확히 대응되지 않는 업종은 임의 매핑하지 않는다.

### 미지원 category_l2

현재 segment_affinity가 없는 업종은 7종, 총 450 POI다.

| category_l2 | POI |
|---|---:|
| 장식품 소매 | 233 |
| 동남아시아 | 111 |
| 구내식당·뷔페 | 47 |
| 도서관·사적지 | 29 |
| 관광지 | 19 |
| 문화시설 | 10 |
| 기타 외국 | 1 |

서울시 추정매출 서비스업종과 직접 대응하기 어렵거나, 관광·문화 계열처럼 상권매출 적용이 부적절한 경우이므로 임의 매핑하지 않고 추천 엔진의 중립 fallback을 사용한다.

---

## 6. quality_score

quality_score는 attr_confidence >= 0.3인 T1 POI만 계산했다.

- 대상: **650 / 800**
- DB 저장: **650**
- min: **0.177215**
- max: **0.912357**
- avg: **0.597874**

검색어가 짧거나 일반적인 POI에서 네이버 `mention_count`가 과대 측정되는 문제가 확인되어, quality 모집단은 attr_confidence >= 0.3으로 제한했다.

해당 모집단의 mention_count P95는 **117,853.7**이며, P95 상한 clipping과 `log1p`를 적용한다.

---

## 7. query_vector_cache

- 목적: 6종
- 날씨: 4종
- 인원 밴드: 3종
- 총 캐시: **6 × 4 × 3 = 72행**
- embedding: **72 / 72**
- 모델: **BAAI/bge-m3, 1024차원**

인원 밴드:

- 1 = 1~2명
- 2 = 3~4명
- 3 = 5명 이상

---

## 8. Citydata 실시간 데이터

GitHub Actions의 scheduled trigger가 불규칙하게 실행되는 문제가 확인되어,
실시간 수집 스케줄러를 Cloudflare Workers Cron Trigger로 보완했다.

현재 구성:

- Cloudflare Cron: 15분마다 실행
- Cloudflare Worker가 GitHub `workflow_dispatch` API 호출
- `poll_citydata`는 workflow당 1회 실행
- GitHub 자체 cron은 시간당 1회 백업용으로 유지

Cloudflare 적용 후 GitHub Actions에서 `workflow_dispatch` 실행이 약 15분 간격으로
연속 생성되고 있으며, 각 polling job은 약 30~40초 내 정상 완료되는 것을 확인했다.

따라서 기존 GitHub scheduled trigger 지연 문제를 외부 스케줄러를 통해 해결했으며,
15분 단위 Citydata 자동 polling이 정상 동작하는 것을 확인했다.

---

## 9. Citydata 연령 baseline 후보

`hotspot_snapshot.age_rates` 누적 **2,122 snapshot**을 사용해 실제 연령 분포 baseline 후보를 계산했다.

각 snapshot의 대표 인구는 `(ppltn_min + ppltn_max) / 2`로 두고 인구 가중 평균을 계산했다.

```python
BASELINE_AGE_RATE = {
    10: 0.047717,
    20: 0.272665,
    30: 0.226391,
    40: 0.167909,
    50: 0.133623,
    60: 0.084339,
}
```

주의:

- Citydata는 0~9세와 70대 이상도 별도 제공한다.
- B 엔진의 사용자 age_band 계약은 10~60이므로 해당 6개 밴드만 제공한다.
- 각 값은 전체 인구 대비 비율이므로 10~60끼리 합이 1이 되도록 재정규화하지 않는다.
- 실제 B 엔진 상수 변경은 B 담당자가 수행한다.

---

## 10. business_hours

현재 확보한 상가정보·TourAPI·프로젝트 CSV에는 신뢰할 수 있는 영업시간 컬럼이 존재하지 않는다.

따라서:

- `business_hours`: **0 / 800 T1**
- 업종별 임의 기본시간을 실제 영업시간처럼 DB에 저장하지 않음
- 현재는 NULL을 유지하고 추천 엔진의 “영업시간 모름” fallback을 사용

이는 known limitation으로 남긴다.

---

## 11. roleA/common placeholder 점검

다음 파일은 0 byte다.

- `roleA/common/config.py`
- `roleA/common/http.py`
- `roleA/common/llm.py`

전체 `roleA` Python 코드에서 import/참조 여부를 검색한 결과 **참조 없음**을 확인했다.

현재 실행되는 파이프라인에는 영향을 주지 않는 placeholder로 판단하며, W5에서 임의 구현하거나 삭제하지 않는다.

---

## 12. 추천 엔진 실주행 검증

Role B `scenario_report` 결과:

- 시나리오: **20개**
- 결과 반환: **20 / 20**
- 각 시나리오 결과: **5건**
- 인용: 각 **5건**
- pipeline latency:
  - p50: **3,290 ms**
  - p95: **3,942 ms**

| 항목 | 가중치 | 상태 | 평균 표준편차 |
|---|---:|---|---:|
| segment_affinity | 0.22 | OK | 0.0951 |
| purpose_match | 0.22 | OK | 0.1031 |
| taste_similarity | 0.16 | OK | 0.0329 |
| context_fit | 0.13 | OK | 0.0164 |
| live_segment_match | 0.10 | OK | 0.0162 |
| quality | 0.09 | OK | 0.1221 |
| crowd_fit | 0.08 | OK | 0.0335 |

**순위를 실제로 가르는 가중치: 1.00 / 1.00**

`check_data_readiness`는 전체 6,644 POI를 분모로 채움률을 평가하므로 T1 전용 속성은 낮게 표시된다. 반면 `scenario_report`는 실제 추천 후보 안에서 각 점수가 변하는지를 확인한다. 현재 실제 추천 경로에서는 모든 점수 항이 순위에 기여하고 있다.

---

## 14. 결론

W4~W5 데이터 파이프라인의 핵심 입력은 모두 생성·적재되었다.

특히 `segment_affinity`, `tag_vector`, `review_chunk.embedding`, `quality_score`, `query_vector_cache`가 실제 추천 엔진에 연결되었고, 20개 실주행 시나리오에서 모든 스코어 항이 후보 간 순위를 실제로 변화시키는 것을 확인했다.

현재 가장 큰 known limitation은 영업시간 데이터 부재이며, 나머지 미지원 데이터는 근거 없는 임의 보간보다 NULL/중립 fallback을 선택해 데이터 신뢰도를 우선했다.
