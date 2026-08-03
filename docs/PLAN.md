# 용산 컨텍스트 기반 장소 추천 서비스 — 기획 및 설계

> 코드명: **YONGSAN-PLACE-AGENT**
> 대상 지역: **서울 용산구 전역 (16개 행정동)**
> 팀 규모: 3인 · 기간: **6주**
> 최종 산출물: **배포된 웹 서비스**
> 예산: **0원 (전 구성요소 무료 티어)**
> 작성일: 2026-08-03 (rev.3 — 6주 · 무제로 예산 반영)
> 문서 상태: 설계 확정본 (구현 착수 전)

---

## 0. 한 줄 정의

> **"지금의 나(나이·성향)와 지금의 상황(목적·인원·날씨·시간)에 맞는 용산의 장소를, 실제 리뷰 근거와 함께 3~5곳 추천한다."**

### 0.1 하드 제약 (모든 설계 판단의 상위 규칙)

| 제약 | 귀결 |
|---|---|
| **기간 6주** | M8(랭커 학습) 삭제 · 커버리지 T1 단일 티어 · W1에 배포 파이프라인부터 뚫는다 |
| **비용 0원** | **결제수단 등록이 필요한 서비스는 전부 배제.** Google Places API·Railway 탈락 (§9.2) |
| **LLM 무료 가정** | 무료 티어는 **분당/일일 rate limit**이 병목이다. 배치는 체크포인트+재개, 온라인은 캐시+폴백 필수 (§9.3) |

> **"무료"의 정의를 팀에서 통일할 것:** 이 문서는 *결제수단 등록 없이, 사용량 초과 시 과금이 아니라 차단되는* 서비스만 무료로 취급한다. 신용카드를 걸어두는 크레딧 방식(Google Cloud, Fly.io 등)은 실수 한 번에 과금되므로 쓰지 않는다.

---

## 1. 기획 재정의

### 1.1 원안과 변경점

| 항목 | 원안 | 확정안 | 변경 이유 |
|---|---|---|---|
| 개인화 근거 | "비슷한 사람들이 많이 간 곳" (협업 필터링) | **인구통계 세그먼트 소비 통계** (서울시 상권분석) | 개인 단위 방문 로그가 존재하지 않음. 서비스 초기 로그 0건 |
| 추천 순서 | ① 좌표 추천 → ② 그 안의 장소 | **처음부터 POI 단위 후보 생성**, 상권 인기도는 점수 항으로 | 좌표 선확정 시 경계 밖 우수 후보 소실 + 1단계 오차가 복구 불가 |
| RAG 역할 | 리뷰를 읽고 장소를 **선별** | 리뷰는 **오프라인 배치로 속성 추출**, RAG는 최종 5곳의 **근거 인용·설명 생성** | 요청마다 수백 개 리뷰를 LLM에 태우면 응답 10초+, 비용 폭증, 환각 증가 |
| 날씨 반영 | 점수에 반영 | **하드필터 + 비선형 점수** 이중 적용 | 강수/미세먼지는 임계값에서 행동이 꺾임(선형 아님) |

### 1.2 유지되는 원안의 강점

- 스포티파이식 **온보딩 취향 입력** → 콜드스타트 해결책으로 정확한 판단
- **요청 시점 컨텍스트 입력**(목적·인원) → 추천 품질의 가장 큰 레버
- **실시간 날씨/대기질 반영** → 기존 지도 앱 대비 명확한 차별점
- **리뷰 기반 최종 선별** → 신뢰도 확보 수단 (역할만 조정)

### 1.3 핵심 차별점 (심사·발표용 3줄)

1. 평점순이 아니라 **"당신 세그먼트가 이 시간대에 실제로 소비하는 곳"** 을 판다 (공공 소비 데이터 기반)
2. 비·미세먼지·폭염이 오면 **후보 집합 자체가 바뀐다** (야외 노출도 속성 보유)
3. 추천마다 **실제 리뷰 문장을 인용한 근거**를 제시한다 (블랙박스 아님)

### 1.4 지역 변경: 마포 3개 동 → 용산구 전역

**용산이 이 서비스에 더 유리한 이유 3가지**

| 근거 | 내용 |
|---|---|
| **상권 이질성이 극단적** | 이태원·한남(고급·외국인) / 이촌·서빙고(주거·가족) / 용산역·한강로(대형쇼핑) / 후암·해방촌(로컬감성) — 세그먼트별 추천이 **눈에 띄게 달라진다**. 마포 3개 동은 대비가 약했다 |
| **실내 대형시설이 많다** | 아이파크몰, 용산역, 국립중앙박물관, 전쟁기념관 — **우천/폭염 시 대체 추천 시나리오**가 강력하게 시연된다 |
| **야외 자원도 풍부** | 용산가족공원, 한강공원, 남산, 경리단길 — `outdoor_exposure` 스펙트럼이 0~1 전 구간에 고르게 분포 |

**대신 감수해야 하는 것 (§8.3에서 대응)**

- POI 규모가 **10배 이상**으로 증가 → 리뷰 수집·LLM 속성추출 비용 직격
- 구 전체가 도보권이 아님 (남산·한강·철도로 생활권이 물리적으로 분절) → 거리 로직 수정 필요 (§5.1)

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  ONBOARDING (1회)                                            │
│  성별 · 연령 · 취향태그 5문항 → user_profile + taste_vector   │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│  REQUEST  목적 / 인원 / 예산 / 현재좌표 / 방문예정시각          │
└─────────────────────────────────────────────────────────────┘
                            ▼
   ┌────────────────────────────────────────────────┐
   │ ① RETRIEVAL   후보 생성        → 200~500개      │
   │   PostGIS 반경 + 하드필터(영업/수용/우천)         │
   └────────────────────────────────────────────────┘
                            ▼
   ┌────────────────────────────────────────────────┐
   │ ② RANKING     스코어링         → 상위 20개      │
   │   세그먼트 + 목적 + 취향 + 컨텍스트 + 품질 - 거리  │
   └────────────────────────────────────────────────┘
                            ▼
   ┌────────────────────────────────────────────────┐
   │ ③ RAG RERANK  근거 검색 + 설명 → 최종 3~5개     │
   │   pgvector(poi_id 사전필터) → LLM 인용 생성      │
   └────────────────────────────────────────────────┘
                            ▼
   ┌────────────────────────────────────────────────┐
   │ ④ LOGGING     노출·클릭·선택·만족도 전량 기록     │
   │   → 랭킹 모델 학습 데이터로 환류                  │
   └────────────────────────────────────────────────┘
```

**설계 원칙:** 각 단계는 앞 단계보다 **10배 비싸고 10배 적은 대상**을 처리한다. (500개 → SQL, 20개 → 산술, 5개 → LLM)

---

## 3. 데이터 계획

### 3.0 무료 데이터 총괄 (전부 0원)

| # | 데이터 | 출처 | 형식 | 역할 | 우선순위 |
|---|---|---|---|---|---|
| 1 | **상가(상권)정보** | 공공데이터포털 (소상공인시장진흥공단) | CSV | **POI 백본** — 이게 없으면 추천 대상이 없다 | 🔴 필수 |
| 2 | **서울시 실시간 도시데이터** | 서울 열린데이터광장 `OA-21285` | API | 날씨·대기질·**실시간 혼잡도·연령구성·12h 예측** | 🔴 필수 |
| 3 | **상권분석서비스 — 추정매출** | 서울 열린데이터광장 | CSV | **세그먼트 선호도** (CF 대체재) | 🔴 필수 |
| 4 | **상권분석서비스 — 영역(폴리곤)** | 서울 열린데이터광장 | SHP/CSV | POI ↔ 상권 **공간 조인 키** | 🔴 필수 |
| 5 | **네이버 검색 API (블로그·지역)** | 네이버 개발자센터 | API | 리뷰 텍스트 → 속성추출·RAG | 🔴 필수 |
| 6 | **카카오 로컬 / 맵 JS SDK** | 카카오 디벨로퍼스 | API | POI 보정, 지도 UI | 🔴 필수 |
| 7 | **행정동 경계 GeoJSON** | 서울 열린데이터광장 / 국가공간정보포털 | GeoJSON | `dong`·`zone` 태깅 | 🔴 필수 |
| 8 | **기상청 단기예보 API** | 공공데이터포털 | API | **3시간 이상 뒤 예보** (citydata 보완, §3.3.3) | 🟠 권장 |
| 9 | **서울 생활인구 (KT)** | 서울 열린데이터광장 | CSV | 핫스팟 밖 지역의 세그먼트 백업 | 🟠 권장 |
| 10 | **한국관광공사 TourAPI** | 공공데이터포털 | API | 박물관·공원 등 **문화·관광 POI + 이미지** | 🟠 권장 |
| 11 | **지하철 역별 승하차** | 서울 열린데이터광장 | CSV | 접근성 보조 | 🟡 선택 |
| 12 | **에어코리아 측정소 정보** | 공공데이터포털 | API | citydata PM 값 결측 시 폴백 | 🟡 선택 |

**필수 7종만 확보하면 서비스가 돈다.** 8~12는 여유가 생길 때 붙인다. 6주 안에 12개를 다 붙이려 하지 말 것.

> **10번(TourAPI)을 권장에 넣은 이유:** 상가정보에는 국립중앙박물관·전쟁기념관·용산가족공원 같은 **비상업 시설이 없다.** 용산은 이런 곳이 추천 가치가 큰 지역이고, TourAPI는 **대표 이미지까지 무료로 제공**해서 UI 품질이 크게 올라간다. `outdoor_exposure` 판정도 카테고리만으로 거의 정확하다.

### 3.1 POI 백본

| 데이터 | 출처 | 비용 | 갱신 |
|---|---|---|---|
| 상가(상권)정보 | 소상공인시장진흥공단 / 공공데이터포털 | 무료 | 분기 |
| 장소 메타·좌표 보정 | 카카오 로컬 API | 무료 (일 10만 건) | 온디맨드 |
| 영업시간 | 카카오 로컬 + 리뷰 텍스트 추출 | 무료 | 월 1회 |

> ~~Google Places API~~ **삭제.** 리뷰가 포함된 Place Details는 유료 SKU이고 무료 할당을 넘으면 즉시 과금된다. 결제수단 등록 자체가 §0.1 위반이다. 영업시간은 카카오 메타 + 리뷰 텍스트에서 LLM이 추출하는 것으로 대체한다.

### 3.2 세그먼트 선호도 (개인화의 근거)

| 데이터 | 출처 | 제공 축 |
|---|---|---|
| **서울시 상권분석서비스 추정매출** | 서울 열린데이터광장 | 상권 × 업종 × 성별 × 연령대 × 요일 × 시간대 |
| 서울 생활인구 (KT) | 서울 열린데이터광장 | 행정동 × 시간 × 성별 × 5세 연령 |
| 지하철 승하차 / 따릉이 대여 | 서울 열린데이터광장 | 접근성·시간대 혼잡 프록시 |

> 이 세 개가 "비슷한 사람들이 많이 갔던 곳"을 **개인정보 없이** 재현하는 대체재다.

### 3.3 실시간 컨텍스트 — **서울시 실시간 도시데이터(citydata)를 주력으로**

**데이터셋:** [서울시 실시간 도시데이터 (OA-21285)](https://data.seoul.go.kr/dataList/OA-21285/A/1/datasetView.do) · 서울 열린데이터광장 · **공공누리 1유형(무료)** · 매뉴얼 V8.5(2026-04) 기준 정상 서비스

#### 3.3.1 이 데이터의 정확한 성격 (오해 주의)

> ⚠️ **이것은 POI 데이터셋이 아니다.** 서울 주요 **121개 "핫스팟" 지역** 단위의 실시간 현황이다. 개별 상점 목록이 아니라 "이태원 관광특구", "용산역" 같은 **광역 지점**이다.
>
> **용산구 해당 지점은 대략 5~7개**에 불과하다. 추천 후보 목록(POI 백본)으로는 쓸 수 없다. POI 백본은 §3.1의 소상공인 상가정보가 계속 담당한다.
>
> 정확한 지점 목록은 `서울시 주요 121장소 목록.xlsx`(데이터셋 페이지에서 다운로드)에서 **W1에 반드시 확인**하고, 용산 지점명·코드를 `hotspot` 테이블에 하드코딩한다.

#### 3.3.2 제공 항목과 우리 설계에서의 역할

| 응답 블록 | 주요 필드 | 우리 설계에서의 역할 |
|---|---|---|
| `WEATHER_STTS` | `TEMP`, `SENSIBLE_TEMP`, `PRECIPITATION`, `PRECPT_TYPE`, `PM10`, `PM25`, `SUNSET`, `UV_INDEX` | **기상청 + 에어코리아를 한 API로 대체** |
| `LIVE_PPLTN_STTS` | `AREA_CONGEST_LVL`, `AREA_PPLTN_MIN/MAX` | 실시간 혼잡도 → `crowd_fit` (신규) |
| `LIVE_PPLTN_STTS` | `PPLTN_RATE_0`~`PPLTN_RATE_70`, `MALE/FEMALE_PPLTN_RATE` | 🔥 **실시간 세그먼트** → `live_segment_match` (신규, §3.6) |
| `FCST_PPLTN` | 2시간 단위 **12시간 예측** 혼잡도·인구 | 🔥 **방문 예정 시각의 혼잡도 예측** |
| `ROAD_TRAFFIC_STTS` / `PRK_STTS` / `SBIKE_STTS` | 도로소통·주차장·따릉이 | 접근성 보조 (선택) |
| `EVENT_STTS` | 문화행사 | 이벤트 가산점 (선택) |

#### 3.3.3 보완: 기상청 단기예보는 계속 쓴다

citydata의 날씨는 **현재 실황 중심**이고 예보 범위가 짧다. 서비스 원칙이 *"실측값이 아니라 방문 예정 시각의 예보"* 이므로 **3시간 뒤 예보가 필요한 경우 기상청 단기예보 API를 병행**한다.

| 시나리오 | 사용 소스 |
|---|---|
| "지금 나갈래" (2시간 이내) | citydata `WEATHER_STTS` |
| "저녁에 갈 건데" (3시간 이상 뒤) | 기상청 단기예보 API |
| 혼잡도 (모든 경우) | citydata `FCST_PPLTN` |

#### 3.3.4 무료 쿼터 관리 — 폴링 주기 계산

**API 제약: 한 번에 1개 장소씩만 호출 가능.** 용산 지점이 7개면 1회 갱신에 7콜이 든다.

| 폴링 주기 | 일일 호출 수 (7지점) | 판정 |
|---|---|---|
| 5분 | 2,016 | ❌ 기본 쿼터 초과 위험 |
| 10분 | 1,008 | ⚠️ 아슬아슬 |
| **15분** | **672** | ✅ **채택** |

- 혼잡도·날씨는 15분 해상도로 충분하다. 사용자 요청마다 호출하지 않고 **배치로 폴링해 DB에 적재**하고, API는 DB만 읽는다.
- 열린데이터광장 인증키의 일일 한도는 **W1에 실제 발급 화면에서 확인**할 것 (트래픽 증가 신청 가능). 한도가 더 낮으면 30분 주기로 낮춘다.

```sql
CREATE TABLE hotspot_snapshot (
  hotspot_code  TEXT,
  observed_at   TIMESTAMPTZ,
  congest_lvl   TEXT,
  ppltn_min     INT,  ppltn_max INT,
  age_rates     JSONB,      -- {"20": 31.2, "30": 24.8, ...}
  male_rate     REAL,  female_rate REAL,
  weather       JSONB,      -- TEMP, SENSIBLE_TEMP, PRECIPITATION, PM10, PM25, SUNSET ...
  fcst          JSONB,      -- 12시간 예측 배열
  PRIMARY KEY (hotspot_code, observed_at)
);
-- POI ↔ 핫스팟 매핑 (가장 가까운 핫스팟, 반경 1km 이내만)
ALTER TABLE poi ADD COLUMN hotspot_code TEXT;   -- NULL 허용 (커버 밖 POI)
```

### 3.6 실시간 세그먼트 매칭 (citydata가 열어준 신규 신호)

기존 §3.2 세그먼트 선호도는 **과거 통계**다. citydata는 여기에 **현재**를 더한다.

```python
def live_segment_match(hotspot, user):
    """지금 이 지역에 사용자 또래가 실제로 얼마나 있는가"""
    if hotspot is None:                      # 핫스팟 커버 밖 POI
        return None                          # ← 점수에서 제외 (0점 아님)
    rate = hotspot.age_rates.get(str(user.age_band_10), 0)
    base = BASELINE_AGE_RATE[user.age_band_10]   # 서울 전체 평균 비율
    return clip(rate / base / 2.0, 0, 1)

def crowd_fit(hotspot, purpose, visit_at):
    """목적에 따라 혼잡이 호재일 수도 악재일 수도 있다"""
    lvl = hotspot.forecast_congest_at(visit_at)   # FCST_PPLTN 사용
    if purpose in ("데이트", "혼자", "작업"):      # 조용함 선호
        return {"여유": 1.0, "보통": 0.8, "약간 붐빔": 0.5, "붐빔": 0.2}[lvl]
    if purpose in ("친구모임", "회식"):            # 활기 선호
        return {"여유": 0.6, "보통": 0.9, "약간 붐빔": 1.0, "붐빔": 0.8}[lvl]
    return 0.8
```

> **설계 규칙: `live_*` 항은 "가용할 때만 가산"하는 옵셔널 항이다.**
> 용산 POI의 상당수는 121개 핫스팟 반경 밖이라 이 신호가 없다. 없을 때 **0점을 주면 커버 밖 POI가 전멸**한다. `None`이면 가중치를 다른 항에 재분배(renormalize)해야 한다.

**이게 발표에서 가장 강한 카드다.** "과거 통계로 고르고, 실시간 인구 구성으로 검증한다"는 2단 구조는 기존 지도 앱이 하지 않는 것이다.

### 3.4 리뷰 텍스트 — 합법 경로만 사용

| 경로 | 사용 | 비용 | 비고 |
|---|---|---|---|
| **네이버 검색 API — 블로그** | ✅ **주력** | 무료 (일 25,000) | 방문기 본문. 서술이 풍부해 속성 추출에 오히려 유리 |
| **네이버 검색 API — 지역** | ✅ 채택 | 무료 | POI 매칭 · 카테고리 보정 |
| 카카오 로컬 API | ✅ 보조 | 무료 (일 100,000) | 리뷰 미제공, 메타데이터만 |
| ~~Google Places API~~ | ❌ 제외 | **유료** | §0.1 위반 |
| 지도 리뷰 스크래핑 | ❌ 금지 | — | 약관 위반. 발표·경진대회 감점 요인 |

#### 3.4.1 평점이 사라진 문제 — 무엇으로 대체하나

Google Places를 버리면서 **별점(rating)을 잃었다.** 세 가지 무료 신호로 대체한다.

| 대체 신호 | 산출 방법 | 의미 |
|---|---|---|
| `mention_count` | 네이버 블로그 검색 응답의 `total` 값 | **인기도** — 얼마나 많이 언급되는가 |
| `sentiment_score` | LLM 속성추출 시 함께 산출 (0~1) | **만족도** — 후기 논조가 얼마나 긍정적인가 |
| `revenue_affinity` | 상권분석 추정매출 (§3.2) | **실제 소비** — 진짜로 돈을 쓰는가 |

```python
quality = bayes(sentiment_score, n=review_count, C=8) * log1p(mention_count) / LOG_NORM
```

> 이건 타협이 아니라 **오히려 강점이다.** 별점은 조작·편향이 심한 반면, 블로그 후기 논조 + 공공 소비 데이터 조합은 발표에서 *"왜 평점을 쓰지 않는가"* 로 설명할 수 있는 차별점이 된다.

**남는 리스크:** 블로그 후기는 **광고성 글 비중이 높다.** 속성추출 프롬프트에 `is_sponsored` 판정을 넣고, 광고 판정 글은 `sentiment_score` 산출에서 제외한다 (속성 추출에는 계속 사용 — 시설 정보 자체는 유효하므로).

**리스크:** 리뷰 확보가 이 프로젝트 최대 병목. → 대응은 §8.1

### 3.5 직접 생성하는 데이터 (LLM 속성 추출)

공개 데이터에 없지만 서비스에 필수인 값. 리뷰에서 배치 추출한다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `outdoor_exposure` | REAL 0~1 | 0=완전 실내, 1=완전 야외. **날씨 로직의 축** |
| `group_capacity` | INT | 단체 수용 가능 인원 |
| `noise_level` | 1~5 | 조용함 ~ 시끌벅적 |
| `purpose_tags` | TEXT[] | 데이트 / 카공 / 회식 / 혼밥 / 가족 / 반려동물 |
| `wait_intensity` | JSONB | 요일·시간대별 웨이팅 강도 |
| `price_band` | 1~4 | 가격대 |
| `atmosphere_tags` | TEXT[] | 분위기 태그 (취향 벡터 생성용) |
| `sentiment_score` | REAL 0~1 | **별점 대체 신호** (§3.4.1) |
| `is_sponsored` | BOOL | 청크 단위 광고글 판정 → 감성 산출에서 제외 |

---

## 4. 데이터 모델

```sql
-- ============ POI ============
CREATE TABLE poi (
  poi_id              TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  category_l1         TEXT,                    -- 음식 / 카페 / 문화 / 쇼핑 / 자연
  category_l2         TEXT,                    -- 한식, 베이커리카페, 전시 ...
  geom                GEOGRAPHY(POINT, 4326) NOT NULL,
  dong                TEXT,
  commercial_area_id  TEXT,                    -- 상권분석 조인 키
  business_hours      JSONB,
  -- LLM 추출 속성
  outdoor_exposure    REAL    DEFAULT 0.0,
  group_capacity      INT     DEFAULT 4,
  noise_level         SMALLINT,
  purpose_tags        TEXT[],
  atmosphere_tags     TEXT[],
  price_band          SMALLINT,
  wait_intensity      JSONB,
  zone                TEXT,                    -- 생활권 (§13) — ZONE_BARRIER 키
  tag_vector          HALFVEC(1024),           -- 취향 매칭용 (2바이트/차원)
  -- 품질 (별점 대체, §3.4.1)
  sentiment_score     REAL,                    -- 후기 논조 0~1
  mention_count       INT     DEFAULT 0,       -- 블로그 언급량
  review_count        INT     DEFAULT 0,
  quality_score       REAL,                    -- 베이지안 보정 후 최종 품질
  attr_confidence     REAL,                    -- 속성 추출 신뢰도 (리뷰 수 기반)
  tier                SMALLINT DEFAULT 3,      -- 1=수집완료 2/3=미수집
  updated_at          TIMESTAMPTZ
);
CREATE INDEX idx_poi_geom ON poi USING GIST (geom);
CREATE INDEX idx_poi_tagvec ON poi USING hnsw (tag_vector halfvec_cosine_ops);

-- ============ 세그먼트 선호도 ============
CREATE TABLE segment_affinity (
  commercial_area_id  TEXT,
  category_l2         TEXT,
  gender              CHAR(1),                 -- M / F
  age_band            SMALLINT,                -- 20, 25, 30 ... (5세 단위)
  dow_type            SMALLINT,                -- 0=평일 1=주말
  hour_band           SMALLINT,                -- 0~5 (4시간 단위)
  affinity            REAL,                    -- 0~1 정규화 소비강도
  sample_weight       REAL,                    -- 원본 표본 규모
  PRIMARY KEY (commercial_area_id, category_l2, gender, age_band, dow_type, hour_band)
);

-- ============ 리뷰 청크 (RAG) ============
-- 무료 DB 500MB 제약 → POI당 최대 3청크로 요약 압축 (§9.4)
CREATE TABLE review_chunk (
  chunk_id      BIGSERIAL PRIMARY KEY,
  poi_id        TEXT REFERENCES poi(poi_id),
  source        TEXT,                          -- naver_blog
  text          TEXT,                          -- 인용용 원문 발췌 (최대 300자)
  embedding     HALFVEC(1024),                 -- 2바이트/차원
  is_sponsored  BOOL DEFAULT FALSE,
  written_at    DATE
);
CREATE INDEX idx_chunk_poi ON review_chunk (poi_id);
CREATE INDEX idx_chunk_vec ON review_chunk USING hnsw (embedding halfvec_cosine_ops);

-- ============ 사용자 ============
CREATE TABLE user_profile (
  user_id       TEXT PRIMARY KEY,
  gender        CHAR(1),
  age_band      SMALLINT,
  taste_vector  HALFVEC(1024),                 -- 온보딩 태그 임베딩 평균
  taste_tags    TEXT[],
  weather_sensitivity SMALLINT,                -- 부록 A 5번 문항
  created_at    TIMESTAMPTZ
);

-- ============ 쿼리 벡터 사전계산 캐시 (§11.3) ============
CREATE TABLE query_vector_cache (
  purpose       TEXT,
  weather_state TEXT,
  party_band    SMALLINT,
  embedding     HALFVEC(1024),
  PRIMARY KEY (purpose, weather_state, party_band)
);

-- ============ LLM 설명 캐시 (§9.3) ============
CREATE TABLE explanation_cache (
  cache_key   TEXT PRIMARY KEY,                -- hash(purpose,party,weather,zone,top20_ids)
  payload     JSONB,                           -- 생성된 추천 설명·인용
  created_at  TIMESTAMPTZ
);

-- ============ 추천 로그 (학습 데이터) ============
CREATE TABLE recommendation_log (
  log_id        BIGSERIAL PRIMARY KEY,
  user_id       TEXT,
  requested_at  TIMESTAMPTZ,
  context       JSONB,        -- 목적·인원·예산·좌표·날씨 스냅샷
  candidates    JSONB,        -- 노출 POI 배열 + 각 점수 성분 (negative sample)
  clicked       TEXT[],
  selected      TEXT,
  feedback      SMALLINT      -- 사후 만족도 1~5
);
```

> **`candidates`(노출됐지만 선택되지 않은 것)를 반드시 남긴다.** 이게 없으면 로그를 몇 달 모아도 랭킹 모델 학습이 불가능하다.

---

## 5. 추천 로직 상세

### 5.1 ① 후보 생성 — 하드필터

"틀리면 무조건 실패하는 조건"만 넣는다.

```sql
SELECT poi_id
FROM poi
WHERE ST_DWithin(geom, :user_geom, :radius_m)     -- 도보 15분 기본 1200m
  AND is_open_at(business_hours, :visit_at)
  AND group_capacity >= :party_size
  AND (:rain_prob < 0.6 OR outdoor_exposure <= 0.7)   -- 우천 하드컷
  AND (:pm_grade < 4  OR outdoor_exposure <= 0.5)     -- 매우나쁨 하드컷
  AND price_band <= :budget_band
  AND attr_confidence >= 0.3;
```

후보가 30개 미만이면 반경을 1.6배로 확대해 재시도(최대 2회).

**용산 전역 확대에 따른 거리 로직 수정 — 직선거리를 쓰면 안 된다**

용산구는 **남산·한강·경부선 철로**로 생활권이 물리적으로 분절되어 있다. 직선거리 800m라도 철로 반대편이면 실제 도보 20분이 걸린다.

```python
# 생활권(zone) 정의: 남산권 / 이태원·한남권 / 용산역·한강로권 / 이촌·서빙고권 / 청파·원효로권
def distance_cost(user, poi):
    d = haversine(user.geom, poi.geom)
    if user.zone != poi.zone:
        d *= ZONE_BARRIER[(user.zone, poi.zone)]   # 1.3 ~ 2.5 배율
    return d
```

- `ZONE_BARRIER`는 **초기엔 수동 상수표**로 채운다 (5×5 행렬 = 10개 값). 대중교통 API 연동은 M7 이후 선택 과제.
- 대중교통으로 오히려 가까운 구간(예: 이촌↔용산역 = 1정거장)은 배율을 1.0 미만으로 둔다.
- 이 zone 배율 하나가 "직선거리 추천"과 "체감 거리 추천"의 차이를 만든다. **발표에서 설명하기 좋은 디테일이다.**

### 5.2 ② 스코어링

```python
W = {
  "segment_affinity":   0.22,   # 과거 통계 — 내 세그먼트의 상권·업종 소비 강도
  "purpose_match":      0.22,   # 요청 목적 ↔ poi.purpose_tags 일치도
  "taste_similarity":   0.16,   # cosine(user.taste_vector, poi.tag_vector)
  "context_fit":        0.13,   # 날씨·시간 적합도
  "quality":            0.09,   # quality_score (별점 대체, §3.4.1)
  "live_segment_match": 0.10,   # 실시간 — 지금 또래가 있는가 (§3.6) ★옵셔널
  "crowd_fit":          0.08,   # 실시간 — 목적 대비 혼잡도 (§3.6)   ★옵셔널
}
PENALTY = {"distance": 0.05}    # zone 배율 반영 거리 (우천 시 2배)
```

**옵셔널 항 처리 — 이게 틀리면 커버 밖 POI가 전멸한다**

`live_*` 항은 POI가 121개 핫스팟 반경 안에 있을 때만 값이 있다. 없을 때 0점을 주면 **핫스팟 밖 POI가 구조적으로 불리해진다.** 반드시 **가중치를 재정규화**한다.

```python
def total_score(poi, user, ctx):
    terms = compute_terms(poi, user, ctx)          # 일부는 None
    avail = {k: v for k, v in terms.items() if v is not None}
    wsum  = sum(W[k] for k in avail)               # 가용 항의 가중치 합
    score = sum(W[k] * v for k, v in avail.items()) / wsum   # ← 재정규화
    return score - PENALTY["distance"] * distance_penalty(poi, user, ctx)
```

가중치는 **초기 수동 설정 → 로그 축적 후 LightGBM(LambdaRank)로 대체**한다. 학습 데이터 없이 딥러닝 추천 모델을 먼저 얹으면 실패한다.

**context_fit — 비선형 구현**

```python
def context_fit(poi, wx) -> float:
    """기온은 U자형, 미세먼지는 등급 임계값에서 행동이 꺾인다."""
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

**품질 점수 — 별점 없이 산출 (§3.4.1)**

후기 1건이 극찬인 곳이 후기 50건에 평균적인 곳을 이기는 것을 막기 위해 베이지안 보정을 건다.

```python
# 1) 감성 점수 베이지안 보정 (광고글 제외한 청크만 집계)
s_bayes = (C * m + sentiment_score * n_clean) / (C + n_clean)
#   m = 전체 POI 평균 감성, C = 신뢰 임계 후기 수 (권장 8), n_clean = is_sponsored=false 청크 수

# 2) 인기도 결합
quality_score = s_bayes * (log1p(mention_count) / log1p(MENTION_P95))
#   MENTION_P95 = 전체 POI 언급량 95퍼센타일 (상한 클리핑용)
```

`quality_score`는 배치에서 미리 계산해 `poi` 테이블에 저장한다. 온라인에서 계산하지 않는다.

### 5.3 ③ RAG 리랭킹 및 설명 생성

상위 20개에 대해서만 실행.

```
쿼리 문장 구성: "{인원}명 / {목적} / {날씨} / 예산 {밴드}"
  ↓
pgvector 검색 (WHERE poi_id IN (상위20) 사전필터 → 벡터 유사도)
  ↓ POI당 관련 리뷰 청크 최대 3개
  ↓
LLM 프롬프트: [요청 컨텍스트] + [POI 20개 요약 + 인용 후보]
  ↓
출력(JSON): 3~5곳, 각각 { poi_id, 적합도, 추천이유, 인용문 }
```

- 임베딩: **bge-m3** (한국어 성능) / 저장: **pgvector `halfvec`**
- **쿼리 벡터는 온라인에서 계산하지 않는다** — `query_vector_cache`에서 조회 (§11.3). 임베딩 모델이 서버에 없다
- **사전 필터 후 벡터 검색**(pre-filtering) 필수 — 전체 검색 후 필터링하면 정확도 붕괴
- 인용문은 **반드시 `review_chunk.text`에서 그대로 발췌**. LLM 창작 금지를 프롬프트에 명시하고, 후처리에서 원문 포함 여부를 검증
- **LLM 호출 전에 `explanation_cache`를 먼저 조회**한다 (§9.3②). 쿼터 소진 시 템플릿 폴백으로 자동 전환

### 5.4 탐색(exploration) 슬롯

최종 결과 중 **1개는 점수 6~20위에서 무작위 선택**한다. 인기 쏠림을 막고, 랭킹 모델 학습에 필요한 다양한 로그를 확보하기 위함.

---

## 6. API 설계

| Method | Endpoint | 설명 |
|---|---|---|
| `POST` | `/api/onboarding` | 성별·연령·취향태그 → `user_profile` 생성, `taste_vector` 계산 |
| `GET`  | `/api/context/now` | 현재/예정 시각 날씨·대기질 (캐시) |
| `POST` | `/api/recommend` | 메인. 컨텍스트 → 추천 3~5개 + 근거 |
| `POST` | `/api/feedback` | 클릭·선택·만족도 기록 |
| `GET`  | `/api/poi/{id}` | 상세 (속성·리뷰 요약) |

**`POST /api/recommend` 요청/응답**

```jsonc
// Request
{
  "user_id": "u_123",
  "purpose": "데이트",
  "party_size": 2,
  "budget_band": 3,
  "location": { "lat": 37.5607, "lng": 126.9256 },
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
      "distance_m": 430,
      "score": 0.87,
      "score_breakdown": {
        "segment": 0.91, "purpose": 0.88, "taste": 0.79,
        "context": 0.95, "quality": 0.72, "distance": 0.36,
        "live_segment": 0.84, "crowd": 0.50
      },
      "reason": "비 예보가 있어 완전 실내 공간 위주로 골랐습니다. 2인 좌석이 넉넉하고 저녁 시간대 20대 후반 방문 비중이 높은 곳입니다.",
      "evidence": [
        { "text": "비 오는 날 창가 자리에서 보는 뷰가 좋아요", "source": "naver_blog" }
      ],
      "is_exploration": false
    }
  ],
  "log_id": 55123
}
```

`score_breakdown`을 응답에 포함시키는 것은 디버깅과 발표 시연 모두에 유용하다.

---

## 7. 배치 파이프라인

| 잡 | 주기 | 내용 |
|---|---|---|
| `ingest_poi` | 분기 | 상가정보 → `poi` upsert, 좌표·상권코드·**zone** 매핑 |
| `collect_reviews` | 월 | **네이버 블로그 검색** → `review_chunk` + `mention_count` |
| `extract_attributes` | 리뷰 갱신 시 | LLM 배치 → 속성 + `sentiment_score` + `is_sponsored` + `attr_confidence` |
| `embed_chunks` | 리뷰 갱신 시 | **로컬/Colab** bge-m3 임베딩 → `review_chunk.embedding` (halfvec) |
| `build_query_cache` | 스키마 변경 시 | 쿼리 72종 임베딩 → `query_vector_cache` (§11.3) |
| `build_affinity` | 분기 | 상권분석 원본 → 정규화 → `segment_affinity` |
| `compute_quality` | 리뷰 갱신 시 | 베이지안 보정 → `poi.quality_score` (§5.2) |
| `poll_citydata` | **15분** | 용산 핫스팟 7지점 폴링 → `hotspot_snapshot` (§3.3.4) |
| `refresh_forecast` | 1시간 | 기상청 단기예보 → 3시간 이상 뒤 예보 캐시 |
| `map_poi_hotspot` | POI 갱신 시 | POI ↔ 최근접 핫스팟 매핑 (반경 1km 이내만) |
| `keepalive_db` | 1일 | Supabase `SELECT 1` — 7일 일시정지 방지 (§9.2) |

> `retrain_ranker`(LightGBM)는 **6주 범위에서 제외**했다 (§9.5). 로그 확보 시간이 나오지 않는다.

**속성 추출 프롬프트 원칙**

- 한 번에 POI 1개의 리뷰 전체를 넣고 **JSON 스키마 강제 출력**
- 근거가 부족한 필드는 `null` 반환을 허용 (추측 금지)
- 리뷰 3개 미만이면 `attr_confidence < 0.3` → **후보 생성에서 자동 제외** (§5.1)
- **광고성 글 판정(`is_sponsored`)을 반드시 함께 요구**한다. 네이버 블로그는 협찬 글 비중이 높고, 이걸 거르지 않으면 `sentiment_score`가 전부 0.9대로 붕괴한다
- **무료 티어 대응**: `poi.attr_extracted_at IS NULL` 인 것만 처리 → 언제 끊겨도 재개 가능 (§9.3①)

---

## 8. 리스크 및 대응

### 8.1 리뷰 데이터 부족 (최대 리스크)

Google Places를 버렸으므로 **네이버 블로그 단일 소스**가 되었다. 리스크가 커졌고, 대응이 더 중요해졌다.

| 대응 | 내용 |
|---|---|
| 1차 | 네이버 블로그를 **쿼리 다변화**로 긁는다 — `"{상호}"`, `"{상호} {동}"`, `"{상호} 후기"`, `"{상호} 웨이팅"` 4종. POI당 목표 8~10건 |
| 2차 | 리뷰 0~2개 POI는 **속성을 카테고리 기본값으로 채우고** `attr_confidence < 0.3` → 후보에서 자동 제외 |
| 3차 | T1 범위를 리뷰 확보된 POI로 한정 (전수 커버 포기, 문서에 명시) |

**보조 신호:** 블로그가 부족한 POI라도 `segment_affinity`(상권분석 매출)와 `outdoor_exposure`(카테고리 기본값)는 채울 수 있다. **속성이 없는 POI를 지우는 게 아니라 순위에서 내리는 구조**여야 커버리지가 붕괴하지 않는다.

### 8.2 규모 대비 시간·쿼터 (용산 전역 + 6주 + 0원의 삼중 제약)

돈이 아니라 **LLM 무료 티어의 rate limit과 6주라는 시간**이 병목이다. 단계적 커버리지로 대응한다.

| Tier | 범위 | 예상 POI | LLM 추출 소요 | 6주 내 |
|---|---|---|---|---|
| **T1** | 핵심 상권 — 이태원1·2동, 한남동, 한강로동, 후암동 | **~800** | 야간 배치 2~3일 | ✅ **필수** |
| **T2** | 준핵심 — 이촌1동, 남영동, 청파동, 원효로1동 | ~700 | 추가 2일 | ⭕ 여유 시 |
| **T3** | 잔여 8개 동 | ~1,500 | — | ❌ **명시적 제외** |

- **POI 좌표·카테고리 적재는 처음부터 용산 전역**(전부 무료 데이터). 시간이 드는 것은 리뷰 수집과 LLM 추출뿐이므로 이것만 티어링한다.
- T2·T3 POI는 `attr_confidence < 0.3`으로 남아 **후보 생성 단계에서 자동 제외**된다 (§5.1 마지막 조건). 별도 분기 코드가 필요 없다.
- 데모·발표 시나리오는 전부 T1 안에서 구성한다. 심사자는 "용산 전역"을 보되 검증은 T1에서 이뤄진다.
- **T1 800개는 하한이 아니라 목표다.** W3 중반에 500개를 못 넘기면 이태원·한남 2개 동으로 더 줄인다. 넓게 얕은 것보다 좁고 깊은 것이 데모에서 이긴다.

> **T3을 "나중에 한다"가 아니라 "안 한다"로 문서에 못박는다.** 6주 프로젝트에서 가장 위험한 것은 끝까지 범위를 열어두는 것이다. 확장 경로가 배선되어 있음을 보이는 것으로 충분하다.

### 8.3 그 외

| 리스크 | 대응 |
|---|---|
| 인기 쏠림 | 탐색 슬롯 1개 고정 (§5.4) |
| 감성점수 편향 (광고글) | `is_sponsored` 판정글은 `sentiment_score` 집계에서 제외 (§3.4.1) |
| 소수 후기 과대평가 | 베이지안 보정 C=8 (§5.2) |
| 오프라인 평가 불가 (로그 0) | 시나리오 20개 + LLM-as-judge + 정성 평가로 시작 → 사용자 테스트 후 선택률 전환 |
| 날씨 효과 과대추정 | 추후 모델 학습 시 요일·계절 통제 변수 필수 (계절과 날씨가 교란) |
| 온보딩 이탈 | 질문 **5개 이하**, 태그 그리드 다중선택 방식 |
| **무료 LLM 쿼터 소진** | 배치=체크포인트 재개 / 온라인=`explanation_cache` + 템플릿 폴백 (§9.3) |
| **Render 15분 슬립** | UptimeRobot 5분 핑 (§9.2) |
| **Supabase 7일 일시정지** | `keepalive_db` 일일 cron (§7) |
| **무료 티어 조건 변경** | W1에 실검증 + Render→HF Spaces 백업안 확보 (§11.2) |
| 개인정보 | 수집 항목 최소화(성별·연령대만, 생년월일 미수집), 좌표는 로그에 격자 단위로 저장 |
| **public repo 시크릿 유출** | `gitleaks` 프리커밋 훅 + 플랫폼 환경변수만 사용 (§11.4) |

---

## 9. 기술 스택 (전 구성요소 무료)

### 9.1 스택

| 레이어 | 선택 | 무료 조건 |
|---|---|---|
| API | FastAPI (Python 3.11+) | — |
| DB | PostgreSQL + **PostGIS** + **pgvector** | Supabase Free 500MB |
| 임베딩 | bge-m3 (1024차원, **halfvec** 저장) | **로컬/Colab에서 배치 실행** — 서버 상주 없음 |
| LLM | (팀 조달, 무료 가정) | §9.3 운용 규칙 필수 |
| 랭커 | 수동 가중합 (**LightGBM은 6주 범위 밖**) | — |
| 배치 | GitHub Actions cron | public repo = 분 수 무제한 |
| 프론트 | Next.js (App Router) + TypeScript | Vercel Hobby |
| 지도 UI | 카카오맵 JS SDK | 무료 (도메인 제한 필수) |
| 배포 | **Vercel + Render + Supabase** | §11 |
| 모니터링 | UptimeRobot | 무료 50 모니터 |

### 9.2 무료 티어 구성 및 탈락 근거

| 용도 | 채택 | 무료 한도 | 제약 | 탈락한 대안과 이유 |
|---|---|---|---|---|
| 프론트 | **Vercel Hobby** | 무제한 배포, 100GB 대역폭 | **비상업적 용도만** — 학생·경진대회는 해당 | — |
| API 서버 | **Render Free** | 750 인스턴스시간/월 | 15분 무접속 시 슬립 → 콜드스타트 ~1분 | ~~Railway~~ **무료 티어 없음 (트라이얼 크레딧 소진 후 유료)** / ~~Fly.io~~ 결제수단 필수 |
| DB | **Supabase Free** | 500MB, PostGIS·pgvector 모두 지원 | **7일 무접속 시 프로젝트 일시정지** | ~~Neon~~ PostGIS 조합 불확실 |
| 배치 | **GitHub Actions** | public repo 무제한 / private 2,000분 | — | — |
| 슬립 방지 | **UptimeRobot Free** | 5분 간격 핑 | — | GitHub Actions cron으로 하면 private repo 2,000분 초과 |
| 에러추적 | Sentry Developer | 5,000 이벤트/월 | 선택 사항 | — |
| 도메인 | `*.vercel.app` | 무료 | 커스텀 도메인은 유료 → **쓰지 않는다** | — |

> ⚠️ **무료 티어 조건은 자주 바뀐다.** W1에 각 서비스 가입하면서 위 표를 실제 화면과 대조하고, 달라진 항목은 이 문서를 갱신할 것. 특히 **결제수단 등록을 요구하는 화면이 나오면 그 서비스는 즉시 후보에서 제외**한다 (§0.1).

**슬립 대응 2중 장치**

1. UptimeRobot이 5분마다 `/health`를 호출 → Render 인스턴스 상시 가동 (월 ~720시간, 750시간 한도 내)
2. GitHub Actions가 매일 1회 Supabase에 `SELECT 1` → 7일 일시정지 방지

### 9.3 LLM 무료 티어 운용 규칙 (이게 없으면 데모 당일 터진다)

무료 LLM의 병목은 비용이 아니라 **분당/일일 호출 제한**이다. 세 가지 장치로 방어한다.

**① 배치(속성추출) — 체크포인트 + 재개**

```python
# poi.attr_extracted_at 이 NULL 인 것만 처리 → 언제 끊겨도 이어서 재개
# 429 응답 시 exponential backoff, 일일 한도 도달하면 정상 종료 후 다음날 재실행
```

800개 POI를 하루 200개씩 처리해도 4일이면 끝난다. **밤에 돌린다.**

**② 온라인(설명 생성) — 캐시 우선**

```
cache_key = hash(purpose, party_band, weather_state, zone, top20_poi_ids)
→ explanation_cache 히트 시 LLM 호출 0회
```

시나리오가 반복되는 데모 환경에서는 **히트율이 90%를 넘는다.**

**③ 폴백 — LLM 없이도 서비스가 돈다**

일일 한도 소진 시 `score_breakdown` 기반 **템플릿 문장**으로 자동 전환한다.

```python
def template_reason(poi, wx, ctx):
    parts = []
    if wx.rain_prob > 0.5 and poi.outdoor_exposure < 0.3:
        parts.append("비 예보가 있어 실내 공간 위주로 골랐습니다")
    if poi.segment_score > 0.8:
        parts.append(f"{ctx.age_band}대 {ctx.gender_label}의 이 시간대 방문 비중이 높습니다")
    if poi.purpose_score > 0.8:
        parts.append(f"{ctx.purpose}에 적합하다는 후기가 많습니다")
    return ". ".join(parts) + "."
```

> **발표 당일 규칙: 리허설로 `explanation_cache`를 미리 채운다.** 시연 시나리오 20개를 전날 밤에 호출해두면 발표 중 LLM 호출이 0회가 되어, 쿼터·네트워크 사고가 원천 차단된다. (§11.5)

### 9.4 500MB DB 안에 들어가는가 — 용량 계산

| 항목 | 계산 | 용량 |
|---|---|---|
| `review_chunk` 벡터 | 800 POI × 3청크 × `halfvec(1024)` 2KB | 4.8 MB |
| HNSW 인덱스 | 벡터의 약 2배 | ~10 MB |
| `review_chunk` 원문 | 2,400 × 300자 × 3바이트 | ~2 MB |
| `poi` (tag_vector 포함) | 5,000행 × ~2.5KB | ~13 MB |
| `segment_affinity` | 용산 상권 × 업종 × 세그먼트 (희소) | ~20 MB |
| `recommendation_log` | 로그 2,000건 | ~5 MB |
| **합계** | | **~55 MB** |

500MB 대비 **여유 9배**. T2까지 확장해도 안전하다.

**용량을 지키는 두 가지 설계 결정**

- `VECTOR(1024)`(4바이트/차원) 대신 **`HALFVEC(1024)`(2바이트/차원)** — 검색 품질 손실은 무시할 수준이고 용량은 절반
- 리뷰 원문을 통째로 저장하지 않고 **POI당 3청크로 요약 압축** — 인용에 필요한 발췌만 남긴다

### 9.5 6주 범위에서 잘라낸 것

| 제외 | 이유 | 문서상 처리 |
|---|---|---|
| LightGBM 랭커 학습 | 로그 확보 시간 부족 | "확장 경로 배선됨"으로 §12 각주 |
| Google Places 연동 | 유료 | §3.1 삭제 근거 명시 |
| 커스텀 도메인 | 유료 | `*.vercel.app` 사용 |
| T3 8개 동 커버리지 | 시간 | §8.2에 **명시적 제외**로 기재 |
| 대중교통 소요시간 API | 6주 내 통합 부담 | `ZONE_BARRIER` 수동 상수표로 근사 (§5.1) |

---

## 10. 팀 역할 분담 (3인)

### 10.1 분담 원칙

> **레이어로 나누되, 계약(contract)을 먼저 고정하고 병렬화한다.**

3인 프로젝트의 최대 실패 원인은 역할이 겹치는 것이 아니라 **B가 A를 기다리고 C가 B를 기다리는 직렬화**다. 이를 막기 위해:

1. **W1에 셋이 함께** DB 스키마 DDL(§4) + OpenAPI 스펙(§6) + 시드 POI 100개를 확정한다.
2. 그 시점부터 **A는 실데이터를, B는 시드데이터를, C는 목(mock) API를** 상대로 각자 진행한다.
3. **매주 수요일 = 통합일.** 실브랜치 병합 + 전체 흐름 1회 구동. 통합을 미루면 마지막 주에 전부 터진다.

### 10.2 역할 정의

| | **A — 데이터 엔지니어링** | **B — 추천 엔진 · 백엔드** | **C — 프론트엔드 · 배포 · 평가** |
|---|---|---|---|
| **핵심 질문** | "데이터를 어떻게 채우나" | "무엇을 추천하나" | "어떻게 보여주고 띄우나" |
| **소유 테이블** | `poi`, `review_chunk`, `segment_affinity` | `user_profile`, 스코어링 로직 | `recommendation_log` (분석 관점) |
| **주요 작업** | · 상가정보 → POI 적재<br>· Google/네이버 리뷰 수집<br>· **LLM 속성추출 배치**<br>· 상권분석 → `segment_affinity` 정규화<br>· bge-m3 임베딩 배치 | · 후보생성 SQL (PostGIS)<br>· **스코어링 5항 구현**<br>· `context_fit` 비선형 로직<br>· RAG 리랭킹 + 인용 검증<br>· FastAPI 엔드포인트 5종 | · Next.js 온보딩·추천 UI<br>· 카카오맵 지도 뷰<br>· **Vercel/Render/Supabase 배포**<br>· GitHub Actions CI · UptimeRobot<br>· 평가 시나리오 20개 · 사용자 테스트 |
| **담당 마일스톤** | M1, M2, M3 | M5, M6 | M4(연동), M7, 배포 |
| **필요 역량** | Python, API 연동, 데이터 정제 | SQL/PostGIS, 추천로직, LLM | TypeScript/React, 인프라 |
| **주 산출 지표** | POI 커버리지, `attr_confidence` 분포 | 응답시간, 추천 적중률 | 배포 가동률, 사용자 로그 수 |

### 10.3 공동 소유 (3인 합의 필요)

| 항목 | 이유 |
|---|---|
| DB 스키마 (§4) | 셋 다 읽고 씀. **변경 시 반드시 3인 합의 + 마이그레이션 파일** |
| API 스펙 (§6) | B가 제공하고 C가 소비. 스펙 변경은 PR로만 |
| 스코어링 가중치 | A의 데이터 품질 + B의 로직 + C의 평가 결과가 모두 반영 |
| 발표 시나리오 | 데모에서 무엇을 보여줄지 = 전원의 작업 우선순위를 결정 |

### 10.4 대기 방지 장치 (이게 실제로 프로젝트를 살린다)

| 상황 | 장치 |
|---|---|
| C가 API를 기다림 | **W1에 목 서버 제공.** FastAPI에 하드코딩 응답 반환 엔드포인트를 B가 먼저 배포 |
| B가 실데이터를 기다림 | **시드 100 POI + 시드 리뷰를 A가 W1에 커밋.** `seeds/*.json`으로 레포에 포함 |
| A가 API 키 발급을 기다림 | **W0에 전원이 각자 발급 신청** (공공데이터포털은 승인에 1~2일 걸림) |
| LLM 추출 배치가 오래 걸림 | A가 백그라운드로 돌리는 동안 `segment_affinity` 작업 병행 |

### 10.5 인원 조정 시

- **역량이 한쪽에 몰린 팀이면**: C(프론트/배포)를 가장 프론트에 익숙한 사람에게 주고, 나머지 둘이 A·B를 나눈다. A·B는 둘 다 Python이라 교차 리뷰가 쉽다.
- **한 명이 이탈하면**: **T2 커버리지 → M6(RAG 인용검증) → 사용자 테스트 순으로 버린다.** M0~M5(룰 기반 추천 + 배포)는 절대 줄이지 않는다. 이게 "동작하는 서비스"의 하한선이다.

---

## 11. 배포 아키텍처

### 11.1 구성

```
   [사용자 브라우저]
          │
          ▼
┌────────────────────────────┐
│  Vercel Hobby              │   Next.js (App Router)
│  yongsan-place.vercel.app  │   온보딩 · 추천 UI · 카카오맵
└──────────┬─────────────────┘
           │  HTTPS / JSON
           ▼
┌────────────────────────────┐        ┌──────────────────┐
│  Render Free               │◀───────│  UptimeRobot     │
│  FastAPI 컨테이너           │  5분핑  │  슬립 방지        │
│  추천 엔진 · RAG            │        └──────────────────┘
└──────────┬─────────────────┘
           │
           ▼
┌────────────────────────────┐        ┌──────────────────┐
│  Supabase Free (500MB)     │◀───────│  GitHub Actions  │
│  PostGIS + pgvector        │  배치   │  cron            │
└────────────────────────────┘        └────────┬─────────┘
                                               │
                        ┌──────────────────────┼──────────────────┐
                        ▼                      ▼                  ▼
              기상청/에어코리아 API      네이버 검색 API      LLM (무료 티어)
                                                          + 로컬 bge-m3 임베딩
```

**모든 박스가 무료 티어다.** 결제수단을 등록하는 곳은 한 군데도 없다.

### 11.2 선택 근거

| 선택 | 이유 | 탈락 대안과 이유 |
|---|---|---|
| **Vercel Hobby** (프론트) | Next.js 1급 지원, PR 프리뷰 URL 자동 생성 → 팀 리뷰가 쉬움. 무료 | — |
| **Render Free** (API) | FastAPI 컨테이너 상주 → **DB 커넥션 풀 유지 가능**. 결제수단 없이 무료 | **~~Railway~~ — 무료 티어가 없다** (트라이얼 크레딧 소진 후 유료). ~~Vercel Python Functions~~ — 콜드스타트 + 풀 유지 불가. ~~Fly.io~~ — 결제수단 필수 |
| **Supabase Free** (DB) | PostGIS·pgvector **둘 다 지원**, 500MB로 충분 (§9.4) | ~~Neon~~ — PostGIS 조합 확인 부담 |
| **GitHub Actions** (배치) | 무료(public repo), 레포와 동일 위치. 규모상 Airflow 불필요 | — |
| **UptimeRobot** (핑) | Render 15분 슬립 방지. 무료 | GitHub Actions cron — private repo 2,000분 한도 초과 |

**백업안:** Render 무료 조건이 바뀌면 **Hugging Face Spaces (Docker SDK)** 로 옮긴다. 무료 CPU 2vCPU/16GB, 슬립 기준이 48시간으로 훨씬 관대해 오히려 유리할 수 있다. W1에 Render 가입 화면에서 결제수단을 요구하면 즉시 이쪽으로 전환한다.

### 11.3 임베딩 모델을 온라인에 띄우지 않는다 (중요)

bge-m3는 약 2GB다. API 서버에 상주시키면 인스턴스 비용이 몇 배가 된다.

**해법: 쿼리 벡터를 사전 계산해 캐시한다.**

사용자 요청의 쿼리는 유한한 조합이다.

```
목적 6종 × 날씨상태 4종 × 인원밴드 3종 = 72개
```

72개 쿼리 문장의 임베딩을 **배치에서 미리 만들어 테이블에 저장**하면, 온라인에서는 조회만 하면 된다. 임베딩 서버가 아예 필요 없다.

스키마는 §4에 정의되어 있고, `build_query_cache` 배치(§7)가 채운다. 임베딩 계산은 **팀원 PC 또는 Colab 무료 GPU**에서 돌리고 결과 벡터만 DB에 적재한다.

> 자유 텍스트 입력을 나중에 추가하게 되면 그때 임베딩 워커를 붙인다. **6주 범위에서는 넣지 않는다.**
>
> 무료 티어 관점에서도 이게 결정적이다. Render Free는 메모리가 제한적이라 **2GB 모델을 상주시키면 애초에 뜨지 않는다.**

### 11.4 환경 분리

무료 티어에서는 **환경을 3개로 나눌 여유가 없다.** Supabase 프로젝트를 2개 만들면 슬립 관리가 2배가 되므로 2단계로 줄인다.

| 환경 | 프론트 | API | DB | 용도 |
|---|---|---|---|---|
| `local` | `next dev` | `uvicorn --reload` | **Docker Postgres** (postgis/pgvector 이미지) | 개발·실험 |
| `prod` | Vercel production | Render Free | Supabase Free | 데모·발표 |

- Vercel PR 프리뷰는 **prod API를 바라보게** 둔다 (읽기 위주라 안전). 쓰기 엔드포인트는 프리뷰에서 비활성화.
- 시크릿은 각 플랫폼 환경변수로만 관리. `.env`는 `.gitignore`에, `.env.example`만 커밋.
- **API 키를 프론트에 노출하지 않는다.** 기상청·네이버·LLM 호출은 전부 백엔드 경유. 카카오맵 JS 키만 **도메인 제한을 걸어** 프론트에 둔다.
- 레포는 **public**으로 만든다 (GitHub Actions 분 수 무제한 + 포트폴리오 이점). 따라서 **시크릿이 코드에 절대 들어가면 안 된다** — W1에 `gitleaks` 프리커밋 훅을 건다.

### 11.5 배포 체크리스트

- [ ] ~~커스텀 도메인~~ → `*.vercel.app` 사용 (유료 회피)
- [ ] CORS 화이트리스트 (프론트 도메인만)
- [ ] `/api/recommend` **레이트 리밋** (IP당 분당 10회) — 무료 LLM 쿼터 보호
- [ ] 헬스체크 `/health` + **UptimeRobot 5분 핑 등록**
- [ ] **GitHub Actions 일일 Supabase 핑** (7일 일시정지 방지)
- [ ] LLM 일일 호출 상한 + 초과 시 **템플릿 폴백** 자동 전환 (§9.3③)
- [ ] `gitleaks` 프리커밋 훅 (public repo이므로 필수)
- [ ] 에러 트래킹 (Sentry 무료, 선택)
- [ ] **발표 전날 캐시 워밍** — 시연 시나리오 20개 호출 → `explanation_cache` 충전

> 마지막 두 항목이 발표 사고 방지책이다. UptimeRobot이 콜드스타트 1분을 막고, 캐시 워밍이 LLM 쿼터 사고를 막는다. **무료 티어로 데모하는 프로젝트가 실패하는 경로는 거의 항상 이 둘이다.**

---

## 12. 마일스톤 (6주 · 무료 티어)

### 12.1 주차별 3인 병렬 계획

| 주차 | **A — 데이터** | **B — 추천엔진** | **C — 프론트·배포** | 주말 게이트 |
|---|---|---|---|---|
| **W1** | 시드 POI 100건 수집·커밋<br>API 키 전원 발급 | DDL 작성 · OpenAPI 스펙<br>**목 API 배포** | 레포·모노레포 구조<br>**Vercel+Render+Supabase 개통** | 🚩 **prod에 빈 앱이 떠 있다** |
| **W2** | 용산 전역 POI 적재<br>zone 태깅 | 후보생성 SQL(PostGIS)<br>스코어링 골격 | 온보딩 UI · 상태관리<br>UptimeRobot 등록 | POI 5,000건 적재 완료 |
| **W3** | 네이버 리뷰 수집<br>**LLM 추출 야간배치 착수**<br>POI↔핫스팟 매핑 | `context_fit` · zone 배율<br>**citydata 폴링 + 실시간 세그먼트** | 추천 결과 UI · 카카오맵 | 🚩 **T1 리뷰 500 POI 확보** |
| **W4** | 추출 완료 · 임베딩 배치<br>`segment_affinity` 구축 | **추천 v1 완성 (LLM 0회)** | 로깅 · 피드백 UI | 🚩 **실데이터로 추천이 나온다** |
| **W5** | 품질 점검 · 결측 보정<br>쿼리벡터 72종 사전계산 | **RAG v2 + 캐시 + 폴백** | 통합 · 반응형 · 에러처리 | 전 기능 prod 반영 |
| **W6** | 데이터 리포트 | 가중치 튜닝 | 사용자 테스트 · 캐시 워밍 | 🚩 **리허설 2회 완료** |

### 12.2 마일스톤 완료 기준

| # | 주차 | 단계 | 담당 | 완료 기준 |
|---|---|---|---|---|
| **M0** | W1 | 계약 확정 · **배포 개통** | 전원 | DDL 통과 · OpenAPI 확정 · 시드 100 POI · **prod URL 생존** |
| **M1** | W2 | POI 적재 (용산 전역) | A | 좌표·상권코드 매핑률 95%+ · POI 5,000건± · zone 100% 태깅 |
| **M2** | W3~4 | T1 리뷰수집 + 속성추출 | A | T1 800 POI 중 70%+ 가 `attr_confidence ≥ 0.5` |
| **M3** | W4 | 세그먼트 선호도 | A | 용산 전 상권 × 전 세그먼트 커버 |
| **M4** | W3 | 실시간 컨텍스트 연동 | B | 기상청·에어코리아 폴링 정상 · 30분 캐시 |
| **M5** | W4 | **추천 v1 (LLM 0회)** | B | 응답 300ms · 결과 5개 · zone 배율 반영 |
| **M6** | W5 | 추천 v2 (RAG + 캐시 + 폴백) | B | 인용문 원문 일치율 100% · 응답 3초 · **쿼터 소진 시 폴백 동작 확인** |
| **M7** | W2~5 | 웹 UI + 로깅 | C | 온보딩→추천→피드백 전 흐름 · 로그 200건 |
| **M8** | W6 | 튜닝 · 사용자 테스트 · 발표 | 전원 | 가중치 조정 · 시나리오 20개 리허설 2회 |

### 12.3 6주에 맞추기 위한 핵심 판단 3가지

1. **W1에 배포를 뚫는다.** 최종 산출물이 웹 배포이므로 W1 말에 빈 앱이라도 prod URL이 살아 있어야 한다. **배포는 마지막에 하는 일이 아니라 처음에 뚫어놓는 길이다.** 6주 프로젝트에서 배포를 W5로 미루면 반드시 실패한다.
2. **W4의 추천 v1은 LLM을 한 번도 부르지 않는다.** 이게 서야 RAG의 실제 기여도를 측정할 수 있고, 동시에 **LLM이 없어도 데모가 가능한 안전판**이 된다.
3. **주말마다 게이트(🚩)를 통과하지 못하면 그 자리에서 범위를 줄인다.** 예: W3 게이트 미달 시 T1을 이태원·한남 2개 동으로 축소. 6주에서는 지연을 만회할 여유가 없다 — 범위로만 조정한다.

**리스크가 가장 큰 주는 W3**이다. 리뷰 수집과 LLM 추출이 동시에 걸리고, 무료 쿼터 제약이 처음 부딪히는 지점이다. A가 W2에 여유가 생기면 **리뷰 수집을 W2로 당겨 시작**한다.

---

## 13. 용산구 상권 구조 (개발 참고)

| 생활권(zone) | 포함 동 | 성격 | 서비스상 역할 |
|---|---|---|---|
| **이태원·한남권** | 이태원1·2동, 한남동, 보광동 | 고급 · 외국인 · 나이트라이프 | 20~30대 데이트/모임의 주력. **T1 최우선** |
| **용산역·한강로권** | 한강로동, 남영동 | 대형쇼핑 · 실내 · 오피스 | **우천/폭염 대체 추천의 핵심** (아이파크몰) |
| **후암·남산권** | 후암동, 용산2가동 | 로컬감성 · 언덕 · 카페 | 야외 노출도 높음. 날씨 로직 시연 |
| **이촌·서빙고권** | 이촌1·2동, 서빙고동 | 주거 · 가족 · 한강공원 · 박물관 | 40대+ / 가족 세그먼트 대비군 |
| **청파·원효로권** | 청파동, 원효로1·2동, 효창동, 용문동 | 대학가 · 주거 · 가성비 | 저예산 밴드 대비군 |

- 이 zone 구분이 §5.1 `ZONE_BARRIER` 행렬의 축이 된다.
- **남산·한강·경부선 철로**가 zone 경계와 대체로 일치한다 — 배율 상수를 정할 때 이 지형지물을 기준으로 삼는다.

---

## 14. 다음 액션

| 순서 | 작업 | 담당 | 시점 |
|---|---|---|---|
| 1 | **API 키 전원 발급 신청** — **서울 열린데이터광장(citydata 인증키, 일일 한도 확인)** · 공공데이터포털(상가정보·기상청·TourAPI) · 카카오(로컬+맵) · **네이버 검색** | 전원 | **즉시** (공공데이터포털 승인 1~2일) |
| 1b | **`서울시 주요 121장소 목록.xlsx` 다운로드 → 용산 지점명·코드 확정** | A | **즉시** (§3.3.1) |
| 2 | **무료 티어 계정 개설 + §9.2 표 실검증** — Vercel / Render / Supabase / UptimeRobot<br>→ **결제수단을 요구하면 그 서비스는 즉시 교체** (Render → HF Spaces) | C | 즉시 |
| 3 | LLM 무료 조달 경로 확정 + **분당·일일 한도 실측** → §9.3 배치 속도 산정 | B | 즉시 |
| 4 | public 레포 생성 + 모노레포 구조 (`/api`, `/web`, `/batch`) + **gitleaks 훅** | C | W1 |
| 5 | DB 스키마 마이그레이션 작성 · 3인 리뷰 | 전원 | W1 |
| 6 | OpenAPI 스펙 확정 + 목 서버 배포 | B | W1 |
| 7 | 시드 POI 100건 수집 · `seeds/*.json` 커밋 | A | W1 |
| 8 | **빈 앱 prod 배포 성공** (Vercel + Render + Supabase 연결 확인) | C | **W1 종료 게이트** |
| 9 | T1 리뷰 확보량 실측 → §8.1·§8.2 축소 여부 결정 | A | W3 |

> **1~3번은 문서를 더 읽기 전에 지금 시작할 것.** API 승인 대기와 무료 티어 조건 확인은 코드보다 먼저 끝나야 하고, 여기서 막히면 나머지 계획이 전부 밀린다.

---

## 부록 A. 온보딩 문항 (5문항 이내)

1. 성별 / 연령대 (선택형)
2. 선호 분위기 — 태그 그리드 다중선택 (조용한 / 활기찬 / 감성적인 / 트렌디한 / 로컬한 / 넓은)
3. 주로 가는 목적 — 다중선택 (데이트 / 친구모임 / 혼자 / 가족 / 작업 / 회식)
4. 평소 예산대 — 1~4 밴드
5. 날씨 민감도 — "비 오면 약속을 미루는 편인가?" 3단계 → `context_fit` 개인 가중치로 사용

2·3번 태그를 bge-m3로 임베딩해 평균낸 것이 `user_profile.taste_vector`이며, `poi.tag_vector`(atmosphere_tags + purpose_tags 임베딩 평균)와 동일 공간에 놓여 코사인 유사도로 비교된다.

## 부록 B. 용어

- **세그먼트(segment)**: 성별 × 연령대 × 요일유형 × 시간대의 조합. 개인 로그 없이 개인화를 근사하는 단위
- **야외 노출도(outdoor_exposure)**: 0(완전 실내)~1(완전 야외). 날씨 하드필터와 `context_fit`의 입력
- **사전 필터링(pre-filtering)**: 벡터 검색 전에 `poi_id`로 대상을 좁히는 것. 반대(post-filtering)는 정확도가 붕괴됨
- **탐색 슬롯**: 최적이 아닌 후보를 의도적으로 노출해 학습 데이터 다양성을 확보하는 자리
