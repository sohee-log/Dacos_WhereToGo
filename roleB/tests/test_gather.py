"""왕복 묶기 (`pipeline.gather`) — 2026-08-30.

이 파이프라인의 지연은 쿼리 실행이 아니라 **왕복 횟수**다.
Render(싱가포르) → Supabase(서울) 왕복이 실측 88ms라, 서로 기다릴 이유가 없는
조회를 순서대로 보내면 한 번마다 88ms가 그냥 붙는다.

여기서 보는 것은 세 가지다.
  ① 정말 동시에 나가는가 (순차면 묶는 의미가 없다)
  ② 예외가 삼켜지지 않는가 (503이 200으로 바뀌면 안 된다)
  ③ 결과 순서가 인자 순서와 같은가 (완료 순서로 섞이면 조용히 틀린 값이 붙는다)
"""

from __future__ import annotations

import threading
import time

import pytest

from app.services.pipeline import gather


def test_결과는_인자_순서를_지킨다():
    """완료 순서로 섞이면 프로필 자리에 생활권이 들어간다 — 조용히 틀린다."""

    def slow(v, delay):
        def run():
            time.sleep(delay)
            return v
        return run

    assert gather(slow("a", 0.05), slow("b", 0.0), slow("c", 0.02)) == ["a", "b", "c"]


def test_정말_동시에_나간다():
    """순차면 0.15초, 동시면 0.05초대다. 묶는 이유가 이것뿐이다."""
    barrier = threading.Barrier(3, timeout=2.0)

    def wait_for_others():
        barrier.wait()          # 셋이 다 도착해야 통과한다 = 동시 실행의 증거
        return True

    started = time.perf_counter()
    assert gather(wait_for_others, wait_for_others, wait_for_others) == [True] * 3
    assert time.perf_counter() - started < 1.0


def test_예외는_그대로_올라온다():
    """DatabaseUnavailable이 삼켜지면 라우터가 503을 만들 수 없다."""

    def boom():
        raise RuntimeError("DB에 닿지 못했다")

    with pytest.raises(RuntimeError, match="닿지 못했다"):
        gather(lambda: 1, boom, lambda: 3)


def test_하나면_스레드를_만들지_않는다():
    """묶을 게 없는데 스레드를 띄우면 비용만 붙는다."""
    seen: list[int] = []

    def here():
        seen.append(threading.get_ident())
        return 1

    assert gather(here) == [1]
    assert seen == [threading.get_ident()]
