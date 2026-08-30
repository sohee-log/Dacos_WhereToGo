# 평가 시나리오 20개

> 원본(사람이 읽는 버전)은 이 문서다. 실행 가능한 API 파라미터 버전은
> [`roleB/scenarios/warm_scenarios.json`](../roleB/scenarios/warm_scenarios.json)이며,
> 발표 전날 캐시 워밍(C6-3)과 성능 측정(B6-2)이 그 JSON을 그대로 태운다.
> **이 문서를 고치면 JSON도 같이 갱신해서 B에게 알린다** — 둘이 어긋나면 워밍한
> 시나리오와 리허설 때 보여줄 시나리오가 달라진다.

## 커버리지 (ROLE_C §5 C5-4 축)

- **목적 6종 전부**: 데이트·친구모임·혼자·가족·작업·회식
- **인원**: 1~2명 · 3~4명 · 5명 이상
- **zone 5종 전부**: 이태원 · 용산역 · 이촌 · 후암 · 청파
- **연령 6종**: 10대~60대 · **성별 2종** · **날씨민감도 3종**
- **시간대**: 08시(이른아침) · 10~14시(낮) · 15~20시(저녁) · 22시(심야)

**zone 중 `huam`(후암) · `ichon`(이촌) · `cheongpa`(청파)는 실시간 인구 지점 반경**
**밖**이다. 이 셋에서는 `score_breakdown.live_segment`/`crowd` 키 자체가 없어야
정상이고(→ "해당 없음"으로 그려야지 0으로 그리면 안 됨), `itaewon`·`yongsan_stn`은
반경 안이라 두 키가 숫자로 채워져야 정상이다. **리허설에서 이 구분이 화면에
정확히 나타나는지가 가장 흔히 틀리는 지점이다.**

---

### S01 — 비 오는 금요일 저녁 데이트
- user: 여성 / 20대 / 날씨민감도: 높음
- request: purpose=데이트, party_size=2, budget_band=3~5만원,
           location=이태원1동, visit_at=금 19:00
- zone: itaewon (반경 **안** — live_* 있어야 함)
- weather: 요청 시점 실시간 값. **비 오는 날 실행해야 검증 의미가 있다** —
           맑은 날엔 강수 필터링 자체를 확인할 수 없다.
- **기대 동작**: outdoor_exposure 높은 POI 제외 / 실내 카페·레스토랑 상위 /
                 reason에 "비" 언급 / congest 예측 표시
- **실패 조건**: 야외 테라스가 1위 / 빈 결과 / live_* 없는 POI가 전멸

### S02 — 토요일 낮 친구모임 4인
- user: 남성 / 20대 / 날씨민감도: 보통
- request: purpose=친구모임, party_size=4, budget_band=1~3만원,
           location=이태원동, visit_at=토 13:00
- zone: itaewon (반경 안 — live_* 있어야 함)
- **기대 동작**: 4인 착석 가능한 카테고리(음식점 위주) / 성별·연령 편향 없이
                 다양한 카테고리 노출
- **실패 조건**: 결과 5건 미만 / 전부 같은 카테고리로 쏠림

### S03 — 평일 저녁 회식 8인 (용산역)
- user: 남성 / 40대 / 날씨민감도: 낮음
- request: purpose=회식, party_size=8, budget_band=3~5만원,
           location=한강대로(용산역), visit_at=수 19:00
- zone: yongsan_stn (반경 안 — live_* 있어야 함)
- **기대 동작**: 대규모 인원 수용 가능한 업종(고깃집·술집 등) 상위 노출
- **실패 조건**: 1~2인용 카페·디저트가 상위 / 빈 결과

### S04 — 평일 오전 혼자 작업 (용산역)
- user: 여성 / 30대 / 날씨민감도: 보통
- request: purpose=작업, party_size=1, budget_band=1만원 이하,
           location=한강대로(용산역), visit_at=화 10:00
- zone: yongsan_stn (반경 안 — live_* 있어야 함)
- **기대 동작**: 카페·코워킹 성격 장소 상위 / 콘센트·와이파이 언급 evidence 우선
- **실패 조건**: 시끄러운 술집·회식 장소가 상위

### S05 — 주말 오후 가족 나들이 (이촌)
- user: 여성 / 40대 / 날씨민감도: 높음
- request: purpose=가족, party_size=4, budget_band=1~3만원,
           location=이촌동, visit_at=일 15:00
- zone: ichon (반경 **밖** — live_* 키 자체가 없어야 함, "해당 없음"으로 렌더링)
- **기대 동작**: 가족 동반 적합 장소(공원·키즈 친화 등) / debug 모드에서 live_segment
                 행이 "해당 없음"으로 뜨는지 확인
- **실패 조건**: live_segment/crowd가 0으로 그려짐 (이게 §3-3의 핵심 검증 지점)

### S06 — 지점 밖 · 혼자 저녁 (서빙고)
- user: 남성 / 30대 / 날씨민감도: 낮음
- request: purpose=혼자, party_size=1, budget_band=1만원 이하,
           location=서빙고동, visit_at=목 18:00
- zone: ichon (반경 **밖** — live_* 없어야 함)
- **기대 동작**: 1인 식사 가능한 곳 상위 / live_* "해당 없음" 정상 렌더링
- **실패 조건**: live_* 0으로 렌더링 / 빈 결과

### S07 — 언덕 동네 데이트 (후암)
- user: 여성 / 20대 / 날씨민감도: 보통
- request: purpose=데이트, party_size=2, budget_band=1~3만원,
           location=후암동, visit_at=토 16:00
- zone: huam (반경 **밖** — live_* 없어야 함)
- **기대 동작**: 언덕·좁은 골목 특성상 도보거리 점수가 낮게 나올 수 있음 —
                 distance 항목이 정상적으로 반영되는지 확인
- **실패 조건**: 결과가 0건 (반경 밖이라고 후보 자체가 사라지면 안 됨)

### S08 — 해방촌 친구모임 (후암)
- user: 남성 / 20대 / 날씨민감도: 높음
- request: purpose=친구모임, party_size=3, budget_band=1~3만원,
           location=해방촌(후암동), visit_at=금 20:00
- zone: huam (반경 밖 — live_* 없어야 함)
- **기대 동작**: 로컬 감성 카페·바 위주 / evidence 인용문 정상 표시
- **실패 조건**: evidence 빈 배열인데 "리뷰 근거" 라벨이 뜨는 경우 (§3-2)

### S09 — 청파동 혼밥
- user: 여성 / 50대 / 날씨민감도: 보통
- request: purpose=혼자, party_size=1, budget_band=1만원 이하,
           location=청파동, visit_at=수 12:00
- zone: cheongpa (반경 밖 — live_* 없어야 함)
- **기대 동작**: 점심시간대 1인 식사 장소 상위
- **실패 조건**: 빈 결과 / age_mix_top 관련 필드가 있어야 하는데 누락

### S10 — 원효로 작업 (청파)
- user: 남성 / 30대 / 날씨민감도: 낮음
- request: purpose=작업, party_size=1, budget_band=1~3만원,
           location=원효로(청파동), visit_at=목 14:00
- zone: cheongpa (반경 밖 — live_* 없어야 함)
- **기대 동작**: 카페 위주 결과, distance 점수가 실제 도보거리와 대략 비례

### S11 — 대형 회식 12인 (남영)
- user: 남성 / 50대 / 날씨민감도: 낮음
- request: purpose=회식, party_size=12, budget_band=1~3만원,
           location=남영동(용산역), visit_at=금 20:00
- zone: yongsan_stn (반경 안 — live_* 있어야 함)
- **기대 동작**: 12인 이상 수용 가능한 대형 업장 위주 / congest_now 표시
- **실패 조건**: 소규모 카페가 상위 노출 / party_size가 스코어에 전혀 반영 안 됨

### S12 — 가족 5인 주말 점심 (이촌)
- user: 여성 / 40대 / 날씨민감도: 높음
- request: purpose=가족, party_size=5, budget_band=3~5만원,
           location=이촌동, visit_at=일 12:00
- zone: ichon (반경 밖 — live_* 없어야 함)
- **기대 동작**: 가족 단위 5인 좌석 + 예산 상향 반영된 결과

### S13 — 고예산 데이트 (한남)
- user: 여성 / 30대 / 날씨민감도: 보통
- request: purpose=데이트, party_size=2, budget_band=5만원 이상,
           location=한남동, visit_at=토 19:00
- zone: itaewon (반경 안 — live_* 있어야 함)
- **기대 동작**: 파인다이닝·고급 바 등 상위 예산대 장소 우선 노출
- **실패 조건**: 저예산 장소가 섞여서 1위로 나옴

### S14 — 저예산 친구모임 (청파)
- user: 남성 / 10대 / 날씨민감도: 보통
- request: purpose=친구모임, party_size=2, budget_band=1만원 이하,
           location=청파동, visit_at=금 18:00
- zone: cheongpa (반경 밖 — live_* 없어야 함)
- **기대 동작**: 저예산 카테고리 우선 / 10대 연령대 처리(age_mix_top에 "10대 미만"
                 문구가 나올 수 있음 — null 아닌 문자열 형태 확인)

### S15 — 박물관 앞 가족 (용산동)
- user: 여성 / 60대 / 날씨민감도: 높음
- request: purpose=가족, party_size=3, budget_band=1~3만원,
           location=용산동(국립중앙박물관 인근), visit_at=일 14:00
- zone: ichon (반경 밖 — live_* 없어야 함)
- **기대 동작**: 60대 연령대 반영, age_mix_top "70대 이상" 등 극단 문구 처리 확인

### S16 — 심야 친구모임 (이태원)
- user: 남성 / 20대 / 날씨민감도: 낮음
- request: purpose=친구모임, party_size=4, budget_band=3~5만원,
           location=이태원동, visit_at=토 22:00
- zone: itaewon (반경 안 — live_* 있어야 함)
- **기대 동작**: 심야 영업 업장 위주 / 22시 시점 congest_now 반영
- **실패 조건**: 영업 종료 시간대 장소가 상위 노출

### S17 — 이른 아침 혼자 (용산역)
- user: 남성 / 60대 / 날씨민감도: 보통
- request: purpose=혼자, party_size=1, budget_band=1만원 이하,
           location=한강대로(용산역), visit_at=화 08:00
- zone: yongsan_stn (반경 안 — live_* 있어야 함)
- **기대 동작**: 이른 아침 영업 중인 곳(카페 등) 위주 / 콜드스타트 이후 첫 요청
                 시나리오로도 겸용 가능

### S18 — 점심 회식 6인 (한강로)
- user: 여성 / 50대 / 날씨민감도: 낮음
- request: purpose=회식, party_size=6, budget_band=1~3만원,
           location=한강로(용산역), visit_at=목 12:00
- zone: yongsan_stn (반경 안 — live_* 있어야 함)
- **기대 동작**: 점심 회식 특성상 백반·중식 등 실속 업종 상위

### S19 — 주말 저녁 데이트 (후암)
- user: 여성 / 30대 / 날씨민감도: 높음
- request: purpose=데이트, party_size=2, budget_band=3~5만원,
           location=후암동, visit_at=일 19:00
- zone: huam (반경 밖 — live_* 없어야 함)
- **기대 동작**: 해질녘 시간대 반영(sunset 필드), 야경·뷰 좋은 곳 가중 가능성

### S20 — 평일 낮 작업 (한남)
- user: 남성 / 10대 / 날씨민감도: 보통
- request: purpose=작업, party_size=1, budget_band=3~5만원,
           location=한남동, visit_at=수 11:00
- zone: itaewon (반경 안 — live_* 있어야 함)
- **기대 동작**: 카페·라운지 위주 / 10대 연령대와 작업 목적 조합이 자연스러운지
                 (드문 조합이라 exploration 슬롯이 섞일 수 있음 — `is_exploration:true`
                 확인해볼 것)

---

## 리허설 체크리스트 (C6-4와 연동)

- [ ] 20개 전부 결과 5건 반환 (A6-4 통과 — `roleB/docs/SCENARIO_REPORT.md` 참고)
- [ ] `itaewon`/`yongsan_stn` 시나리오(S01,02,03,04,11,13,16,17,18,20)에서 live_*
      키가 숫자로 채워짐
- [ ] `huam`/`ichon`/`cheongpa` 시나리오(S05~10,12,14,15,19)에서 live_* 키가
      "해당 없음"으로 렌더링됨 (0 아님)
- [ ] S01(비) 실행 시 실내 위주로 바뀌는 게 육안으로 보임 — **발표에서 가장 강한
      카드**, 시각·날씨 바꿔가며 결과가 실제로 바뀌는 걸 직접 보여줄 것
- [ ] 극단 연령(S14 10대, S15 60대) 처리 시 `age_mix_top`이 null이 아닌
      "10대 미만 n%" / "70대 이상 n%" 같은 문자열로 정상 표시
