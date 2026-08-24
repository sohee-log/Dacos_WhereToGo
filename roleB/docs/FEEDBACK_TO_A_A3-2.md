# B → A · A3-2(LLM 속성 추출) 코드 리뷰

> 2026-08-24 · 대상 `#21` (`51a69298`) · `roleA/jobs/extract_attributes.py` 979줄
> 읽는 사람 A(데이터) · 참조 C(프론트)
>
> **DB를 못 봤다.** 이 문서는 전부 **소스 대조**다 — 배치가 실제로 돌아 적재된
> 결과는 `check_data_readiness`로 따로 확인해야 한다(§5). 배치가 이미 돌았으면
> 그 출력을 공유해 달라. 아래 판단 몇 개가 실측으로 바뀔 수 있다.

---

## 요약 세 줄

1. **계약은 맞다.** 태그 어휘 16종이 엔진 상수와 **한 글자도 안 틀리고** 같고,
   `json_schema` + `strict`, 끝 슬래시, `requests` UA — W3 브리핑에서 부탁한 걸 다 지켰다.
   이제 이건 테스트로 박제했다(§6).
2. **`outdoor_exposure`를 NULL로 남긴 판단이 맞다.** 대신 그 전제 위에 서 있던
   엔진 코드 세 곳이 깨져 있어서 B가 고쳤다 — **A는 아무것도 바꿀 필요 없다**(§4).
3. **고쳐야 할 것은 세 가지다.** 저장 안 되는 필드 하나, 의미가 뒤집힌 컬럼 하나,
   안 채우는 컬럼 하나. 셋 다 에러가 아니라 조용히 기능이 사라지는 모양이다.

---

## 1. 🔴 `business_hours_hint` — 뽑아서 버린다

스키마에도 있고(`build_schema`), 프롬프트 규칙 9도 있고, `calculate_confidence`의
9개 필드에도 들어 있다. **그런데 `save_result`의 `UPDATE poi SET ...`에 없다.**

결과가 세 겹이다.

| | |
|---|---|
| `poi.business_hours`가 계속 NULL | `is_open_at()`이 **항상 TRUE** → 영업 종료한 곳이 후보에 그대로 남는다 |
| 토큰을 내고 버린다 | POI당 한 필드씩 800번 |
| **confidence를 깎는다** | 리뷰에 영업시간이 적힌 경우는 드물다 → 대부분 null → 전 건 −0.08 |

세 번째가 제일 나쁘다. **쓰지도 않는 필드가 후보 하드필터의 통과율을 낮추고 있다.**

형태가 안 맞는 건 알고 있다 — DDL의 `business_hours`는
`{"mon": ["10:00","22:00"], ...}` JSONB고 힌트는 자유 문장이다. 그래서 둘 중 하나다.

- **(a)** 힌트를 요일 JSONB로 파싱해서 `business_hours`에 넣는다. (효과 큼 · 일 많음)
- **(b)** 스키마·프롬프트·`calculate_confidence`의 `fields`에서 **빼 버린다.**
  (5분 · confidence가 즉시 올라간다)

지금은 **(b)를 권한다.** 영업시간은 리뷰가 아니라 상가업소 원본이나 지도 API에서
오는 게 맞고, 리뷰에서 뽑은 힌트는 신뢰도가 낮아 어차피 `is_open_at`에 태우기
불안하다. (a)는 A4로 미루자.

---

## 2. 🔴 `review_count = len(chunks)` — 최대 3에서 천장을 친다

```python
review_count = %s   ...   len(chunks)     # chunks는 chunk_indices로 최대 3개
```

`chunks`는 "인용으로 쓸 대표 문장 3개"지 리뷰 수가 아니다. 10건을 읽어도 3이 들어간다.

**지금 당장은 순위에 영향이 없다.** 엔진이 이 컬럼을 후보 SQL로 가져오기만 하고
점수에는 안 쓴다(`quality_term`은 `quality_score`만 본다). 그래서 조용하다.

**터지는 곳은 A4-4 `compute_quality`다.** 품질 점수를 리뷰 수로 만들면 전 POI가
0~3 구간에 몰려 해상도가 사라진다. 배치를 쓰기 **전에** 고치는 게 싸다.

권하는 값은 이미 계산돼 있다 — `calculate_confidence`가 내놓는 `n_clean_reviews`
(relevance ∧ ¬sponsorship). 품질의 분모로 쓰기에도 그게 맞다.

```python
review_count = n_clean_reviews     # 또는 len(items)
```

---

## 3. 🟠 `written_at`을 안 넣는다 — postdate가 이미 손에 있는데

```python
INSERT INTO review_chunk (poi_id, source, text, is_sponsored)   # written_at 없음
```

`item["postdate"]`는 프롬프트에 이미 넣고 있다. INSERT에만 안 실렸다.

엔진의 인용 폴백(쿼리 벡터가 없을 때 = **지금**)이 이렇게 정렬한다.

```sql
ORDER BY rc.is_sponsored, rc.written_at DESC NULLS LAST
```

전 건 NULL이면 이 정렬은 통째로 동점이다. 같은 요청이 요청마다 다른 문장을
인용할 수 있어서, B 쪽에 `chunk_id` 동점 처리를 넣어 **재현 가능하게는** 만들어
뒀다. 다만 "최신 후기 우선"은 A가 이 한 줄을 넣어야 산다.

네이버 `postdate`는 `20240513` 형식이라 `DATE` 캐스팅 한 번이면 된다.

---

## 4. ✅ `outdoor_exposure`를 NULL로 남긴 것 — 맞다. 엔진을 고쳤다

프롬프트 규칙 1("확인할 수 없는 속성은 반드시 null")을 이 컬럼에 적용한 판단이
맞다. DDL 기본값 `0.0`은 "완전 실내"라는 **거짓 관측**이고, 값이 없는 것보다 나쁘다.

다만 그 전제 위에 서 있던 엔진 코드가 세 곳 있었다. 전부 **200이 나가면서 기능만
사라지는** 모양이라 화면으로는 구분이 안 된다. B가 고쳤다(PR 참조).

| | 무엇이 | 고치기 전 |
|---|---|---|
| 🔴 | 후보 하드컷 | `p.outdoor_exposure <= 0.7`에 NULL이 들어가면 3값 논리로 WHERE가 NULL → **비 오는 날 T1이 통째로 후보에서 빠진다.** 에러 없이 최근접 폴백으로 주저앉는다 |
| 🟠 | `check_data_readiness` | `IS DISTINCT FROM 0`이 **NULL을 '채워짐'으로 셌다.** 배치가 돌수록 초록으로 물드는데 순위는 하나도 안 움직인다 — `segment_affinity` 때와 같은 거짓 초록불 |
| 🟠 | 설명 문장 | 모르는 곳에 "비 예보가 있어 **실내** 공간 위주로 골랐습니다"를 붙였다. LLM 프롬프트에도 `야외노출 None`이 그대로 갔다 |

지금은 미관측을 `OUTDOOR_EXPOSURE_UNKNOWN`(=0.0) 한 상수로 정의하고, 후보 SQL과
`context_fit`이 **같은 값**을 쓴다. 값이 0.0이라 모든 날씨 계수가 1로 접혀
정확히 중립이 된다 — *모르는 곳은 날씨로 올리지도 내리지도 않는다.*
말은 다르게 한다. 관측이 있을 때만 "실내"라고 쓰고, 프롬프트에는 `야외노출 미상`이다.

> **부탁 하나.** 배치가 끝나면 **`outdoor_exposure`의 관측률**을 알려 달라.
> 이 서비스의 차별점 2번(*날씨를 보고 후보를 바꾼다*)이 정확히 이 숫자에 걸려 있다.
> 0과 NULL은 둘 다 중립이라, 관측률이 낮으면 비가 와도 순위가 안 바뀐다.
> `check_data_readiness`가 이제 이 값을 따로 찍는다(§5).

---

## 5. attr_confidence — 통과율이 몇 %인지가 전환 판정이다

후보 하드필터가 이 값을 자른다(`ATTR_CONFIDENCE_MIN = 0.30`). A의 식은

```
confidence = max(0, min(n_clean/8, 1.0) − 0.08 × (null인 필드 수, 9개 중))
```

`MAX_RESULTS_PER_POI = 10`이니 clean 7건이면 base 0.875 → null 7개까지 버틴다.
반대로 clean이 4건이면 base 0.5 → **null 2개까지밖에 못 버틴다.** 리뷰가 얇은
POI가 구조적으로 탈락한다는 뜻이고, 그건 의도한 동작이기도 하다.

문제는 그 분포를 아무도 안 보고 있었다는 것이다. 그래서 `check_data_readiness`에
A3-2 전용 섹션을 붙였다. **분모가 위 표와 다르다** — poi 전체(6,644)가 아니라
*추출이 끝난 T1*이다. A3-2는 T1 800건만 대상이라 완주해도 전체 채움률은 12%가
최대고, 그 숫자만 보면 실패한 것처럼 읽힌다.

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"
python -m tools.check_data_readiness
```

찍히는 것

- 추출 완료 `n/800`
- **컬럼별 관측률** (추출 완료분 기준) — `outdoor_exposure` · `purpose_tags` ·
  `noise_level` · `price_band` · `sentiment_score` · `wait_intensity` · …
- `attr_confidence` — `>= 0.30` 통과율 · `>= 0.15` · 평균/중앙값 · 정확히 0인 건수
- **고정 어휘 위반 건수** — 어휘 밖 문자열은 에러가 아니라 *영원한 매칭 실패*다

A의 W4 목표(confidence 0.5 이상 70%)를 못 넘으면 배치가 끝난 뒤에도 후보가 얇아
`low_confidence`로 나간다. 그때는 §1의 (b)가 제일 싼 수단이다.

---

## 6. 잘 되어 있는 것 (그리고 이제 테스트로 박제했다)

| | |
|---|---|
| **어휘 16종이 정확히 일치한다** | `PURPOSE_TAGS` 6 · `ATMOSPHERE_TAGS` 10이 엔진 `constants.py`와 순서까지 같다. `tag_embedding` 16행의 근거이기도 하다 |
| `json_schema` + `strict: true` | 지켰다. enum도 인라인이 아니라 상수 참조라 프롬프트와 스키마가 갈릴 수 없다 |
| `requests` 사용 | Cloudflare의 `Python-urllib` 차단(`error code: 1010`)을 자동으로 피한다 |
| URL 끝 슬래시 | 이 게이트웨이는 실제로 끝 슬래시가 필요하다. 맞다 |
| **POI마다 즉시 commit + `attr_extracted_at IS NULL` 체크포인트** | 429/402로 끊겨도 재실행하면 이어서 간다. 재개 설계가 맞다 |
| `review_relevance`로 동명이인을 거른다 | 짧은 상호명 오탐이 인용으로 나가는 걸 막는다. B의 인용 원문 검증과 방향이 같다 |
| `chunk_indices`를 relevance=true로 제한 | 협찬·무관 문장이 대표 인용이 되지 않는다 |

이걸 지키는지 CI가 보게 했다 — `roleB/tests/test_attr_extraction_contract.py`.
**A의 소스를 직접 파싱해서** 대조한다(상수를 B 쪽에 다시 적으면 그게 또 가정이 된다).
어휘를 늘리거나 UPDATE 컬럼을 바꾸면 여기가 먼저 깨진다.

---

## 7. 그 밖에 · 확인만

| | |
|---|---|
| 🟡 재실행이 임베딩을 지운다 | `save_result`가 `DELETE FROM review_chunk`로 시작한다. A4 `embed_chunks` 뒤에 강제 재추출하면 임베딩이 날아간다. 평소엔 `attr_extracted_at IS NULL`이 걸러서 안 마주친다 |
| 🟡 `--limit` 기본값이 50 | 800건은 `--limit 800`이거나 반복 실행이다. 직렬 ~2.5초 × 800 ≈ 33분(B 실측 기준). 동시 8이면 4분인데, 지금 구조로도 하룻밤이면 충분하다 |
| 🟡 `max_tokens`가 없다 | 게이트웨이 기본값에 맡기고 있다. 리뷰 10건 + boolean 배열 2개면 응답이 길어지는데, 잘리면 **에러가 아니라 JSON 파싱 실패**로 나타난다. 로그에 `ERROR: Expecting ...`이 여러 건이면 이걸 의심한다 |
| 🟡 `empty_result()`에 `review_relevance`가 없다 | 지금 경로에서는 안 터진다(리뷰 0건이면 `calculate_confidence`를 안 부른다). 나중에 호출 순서를 바꾸면 KeyError다 |
| ⬜ `LLM_MODEL` 확인 | `gpt-5.4-nano`는 게이트웨이에서 404다. `.env`가 `gemini-3.5-flash-lite`인지 |

---

## 8. 다음 순서 (B 기준 · 브리핑 §5에서 갱신)

| 순서 | 항목 | 왜 지금 |
|---|---|---|
| 1 | **`tag_embedding` 16행** | 임베딩 16번이면 끝난다. 어휘가 방금 일치 확인됐으니 바로 된다. 취향 항 0.16 + 온보딩 `taste_vector` |
| 2 | `build_affinity` (`segment_affinity`) | **단일 최대 가중치 0.22.** 조인 축(`commercial_area_id` 95.6%)은 준비돼 있다. 조회 축 규약은 브리핑 §A-3 |
| 3 | `embed_chunks` | A3-2가 청크를 넣기 시작했으니 이제 대상이 생겼다. 없으면 인용이 최신순 폴백 |
| 4 | `compute_quality` | 그 전에 §2를 고친다 |
| 5 | `build_query_cache` 72행 | 인용 정확도 |

---

**참고** — [`BRIEF_2026-08-23.md`](BRIEF_2026-08-23.md) · [`HANDOFF_TO_A.md`](HANDOFF_TO_A.md) ·
[`LLM_QUOTA.md`](LLM_QUOTA.md) · [계약 테스트](../tests/test_attr_extraction_contract.py)
