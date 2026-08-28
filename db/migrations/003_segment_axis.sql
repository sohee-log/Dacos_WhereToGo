-- ============================================================================
-- 003 — segment_affinity 조회 축 정정 (age_band 10년 단위 · hour_band 불균등 6구간)
--
-- ⚠️ 공동 소유 영역이다. 초안은 B가 쓰되 **PR + 3인 리뷰**로 반영한다.
--    컬럼을 추가·삭제하지 않는다. 제약과 주석만 바꾼다.
--
-- 왜 필요한가
--   001의 규약은 실제 원본 데이터를 보기 전에 세운 가정이었다.
--   서울시 상권분석 추정매출을 열어 보니 두 축이 다르다.
--
--     age_band   가정 5세 단위(20, 25, 30 …)  →  실제 **10년 단위**(10 … 60)
--     hour_band  가정 균등 4시간(시 // 4)     →  실제 **불균등 6구간**
--                0=00~06 · 1=06~11 · 2=11~14 · 3=14~17 · 4=17~21 · 5=21~24
--
--   축이 어긋나면 조회가 에러를 내지 않는다. **0행이 나오고 affinity 항(0.22)이
--   조용히 중립값으로 접힌다.** 화면으로도 로그로도 구분이 안 된다 —
--   BRIEF_2026-08-23 §2 ①②③과 정확히 같은 부류의 실패다.
--
--   지금 segment_affinity 는 0행이므로(A4-3 `build_affinity.py` 미착수)
--   제약을 거는 데 비용이 없다. 잘못된 축으로 적재되면 INSERT 가 **실패**한다.
--   조용한 0행보다 시끄러운 실패가 낫다.
--
-- 엔진 쪽 대응: roleB/app/constants.py 의 `segment_age_bands` · `hour_band`
--
-- 적용:
--   psql "$DATABASE_URL" -f db/migrations/003_segment_axis.sql
-- ============================================================================

BEGIN;

-- age_band 를 10년 단위로 못박는다. user_profile.age_band 와 같은 축이 된다.
-- 이미 5세 단위(25, 35 …)가 적재돼 있으면 여기서 실패한다 — 그때는 원본에서
-- 10년 단위로 다시 집계해 재적재한다. 부분 보정은 하지 않는다.
ALTER TABLE segment_affinity
    DROP CONSTRAINT IF EXISTS segment_affinity_age_band_check;

ALTER TABLE segment_affinity
    ADD CONSTRAINT segment_affinity_age_band_check
    CHECK (age_band IN (10, 20, 30, 40, 50, 60));

-- hour_band 는 범위(0~5)가 그대로다. 바뀐 것은 각 밴드의 **의미**뿐이라
-- 제약으로는 잡히지 않는다. 주석으로 남긴다.
COMMENT ON COLUMN segment_affinity.age_band IS
    '10년 단위: 10, 20, 30, 40, 50, 60. user_profile.age_band 와 같은 축';

COMMENT ON COLUMN segment_affinity.hour_band IS
    '원본의 불균등 6구간. 0=00~06 1=06~11 2=11~14 3=14~17 4=17~21 5=21~24 (균등 4시간이 아니다)';

COMMENT ON COLUMN segment_affinity.affinity IS
    '해당 상권·업종 매출 중 이 세그먼트의 비중. 0~1 정규화 (원본 매출액이 아니다)';

COMMIT;

-- ============================================================================
-- 적용 확인
-- ============================================================================
-- SELECT DISTINCT age_band FROM segment_affinity ORDER BY 1;   -- 10,20,30,40,50,60
-- SELECT DISTINCT hour_band FROM segment_affinity ORDER BY 1;  -- 0..5
