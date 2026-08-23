import argparse
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from roleA.common.db import get_conn

load_dotenv()

SEOUL_API_KEY = os.getenv("SEOUL_API_KEY")

BASE_URL = "http://openapi.seoul.go.kr:8088"

SEOUL_TZ = ZoneInfo("Asia/Seoul")


def to_int(value):
    """
    숫자 문자열 -> int
    '-', '', None 등은 None
    """

    if value in (
        None,
        "",
        "-",
    ):
        return None

    try:
        return int(float(value))
    except (
        TypeError,
        ValueError,
    ):
        return None


def to_float(value):
    """
    숫자 문자열 -> float
    '-', '', None 등은 None
    """

    if value in (
        None,
        "",
        "-",
    ):
        return None

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def parse_seoul_datetime(value):
    """
    서울시 API:
    '2026-08-21 23:40'

    -> timezone-aware datetime
    """

    if not value:
        return datetime.now(SEOUL_TZ)

    dt = datetime.strptime(
        value,
        "%Y-%m-%d %H:%M",
    )

    return dt.replace(tzinfo=SEOUL_TZ)


def fetch_citydata(
    session,
    hotspot_code,
):
    """
    서울 실시간 도시데이터
    한 hotspot 호출
    """

    url = (
        f"{BASE_URL}/"
        f"{SEOUL_API_KEY}/"
        f"json/"
        f"citydata/"
        f"1/5/"
        f"{hotspot_code}"
    )

    for attempt in range(3):

        try:

            response = session.get(
                url,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            result = data.get(
                "RESULT",
                {},
            )

            result_code = result.get("RESULT.CODE")

            if result_code != "INFO-000":
                raise RuntimeError(
                    "서울 API 오류: "
                    f"{result_code} / "
                    f"{result.get('RESULT.MESSAGE')}"
                )

            citydata = data.get("CITYDATA")

            if not citydata:
                raise RuntimeError("CITYDATA가 없습니다.")

            return citydata

        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
        ):

            if attempt == 2:
                raise

            time.sleep(2**attempt)


def parse_citydata(
    citydata,
):
    """
    API 원본을 hotspot_snapshot
    컬럼 구조로 변환한다.
    """

    population_list = citydata.get("LIVE_PPLTN_STTS") or []

    weather_list = citydata.get("WEATHER_STTS") or []

    if not population_list:
        raise ValueError("LIVE_PPLTN_STTS가 없습니다.")

    population = population_list[0]

    weather = weather_list[0] if weather_list else {}

    # ==========================================
    # 관측 시각
    # ==========================================
    #
    # hotspot_snapshot의 핵심은
    # 실시간 인구/혼잡 정보이므로
    # PPLTN_TIME을 observed_at으로 사용.
    #
    # WEATHER_TIME은 weather JSON 안에
    # 별도로 보존한다.
    # ==========================================

    observed_at = parse_seoul_datetime(population.get("PPLTN_TIME"))

    # ==========================================
    # 연령대
    # ==========================================

    age_rates = {
        "0": to_float(population.get("PPLTN_RATE_0")),
        "10": to_float(population.get("PPLTN_RATE_10")),
        "20": to_float(population.get("PPLTN_RATE_20")),
        "30": to_float(population.get("PPLTN_RATE_30")),
        "40": to_float(population.get("PPLTN_RATE_40")),
        "50": to_float(population.get("PPLTN_RATE_50")),
        "60": to_float(population.get("PPLTN_RATE_60")),
        "70": to_float(population.get("PPLTN_RATE_70")),
    }

    # ==========================================
    # 현재 날씨
    # ==========================================
    #
    # forecast 배열은 fcst로 따로 저장하고
    # 현재 날씨 정보만 weather에 둔다.
    # ==========================================

    weather_current = {
        key: value
        for key, value in weather.items()
        if key
        not in {
            "FCST24HOURS",
            "NEWS_LIST",
        }
    }

    # ==========================================
    # 예측
    # ==========================================
    #
    # 한 컬럼 안에
    # 인구예측 + 날씨예측을 모두 보존
    # ==========================================

    fcst = {
        "population": (population.get("FCST_PPLTN") or []),
        "weather": (weather.get("FCST24HOURS") or []),
    }

    return {
        "hotspot_code": citydata.get("AREA_CD"),
        "hotspot_name": citydata.get("AREA_NM"),
        "observed_at": observed_at,
        "congest_lvl": population.get("AREA_CONGEST_LVL"),
        "ppltn_min": to_int(population.get("AREA_PPLTN_MIN")),
        "ppltn_max": to_int(population.get("AREA_PPLTN_MAX")),
        "age_rates": age_rates,
        "male_rate": to_float(population.get("MALE_PPLTN_RATE")),
        "female_rate": to_float(population.get("FEMALE_PPLTN_RATE")),
        "weather": weather_current,
        "fcst": fcst,
    }


def save_snapshot(
    conn,
    snapshot,
):
    """
    동일 hotspot + 동일 observed_at을
    다시 실행해도 중복되지 않도록
    DELETE + INSERT.

    unique constraint 유무에 의존하지 않는다.
    """

    with conn.cursor() as cur:

        cur.execute(
            """
            DELETE FROM hotspot_snapshot
            WHERE hotspot_code = %s
              AND observed_at = %s
            """,
            (
                snapshot["hotspot_code"],
                snapshot["observed_at"],
            ),
        )

        cur.execute(
            """
            INSERT INTO hotspot_snapshot (
                hotspot_code,
                observed_at,
                congest_lvl,
                ppltn_min,
                ppltn_max,
                age_rates,
                male_rate,
                female_rate,
                weather,
                fcst
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                snapshot["hotspot_code"],
                snapshot["observed_at"],
                snapshot["congest_lvl"],
                snapshot["ppltn_min"],
                snapshot["ppltn_max"],
                Jsonb(snapshot["age_rates"]),
                snapshot["male_rate"],
                snapshot["female_rate"],
                Jsonb(snapshot["weather"]),
                Jsonb(snapshot["fcst"]),
            ),
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    if not SEOUL_API_KEY:
        raise ValueError("SEOUL_API_KEY가 .env에 없습니다.")

    conn = get_conn()

    try:

        # ==========================================
        # hotspot 목록
        # ==========================================

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    code,
                    name
                FROM hotspot
                ORDER BY code
                """)

            hotspots = cur.fetchall()

        if args.limit is not None:
            hotspots = hotspots[: args.limit]

        print(
            "수집 대상 hotspot:",
            len(hotspots),
        )

        session = requests.Session()

        success = 0
        failures = []

        for i, (
            code,
            db_name,
        ) in enumerate(
            hotspots,
            start=1,
        ):

            try:

                citydata = fetch_citydata(
                    session,
                    code,
                )

                snapshot = parse_citydata(citydata)

                print(
                    f"[{i}/{len(hotspots)}] "
                    f"{code} / "
                    f"{db_name} "
                    f"→ "
                    f"{snapshot['congest_lvl']} / "
                    f"{snapshot['ppltn_min']}~"
                    f"{snapshot['ppltn_max']} / "
                    f"{snapshot['observed_at']}"
                )

                if args.dry_run:

                    print("  [DRY RUN] DB 저장 생략")

                else:

                    save_snapshot(
                        conn,
                        snapshot,
                    )

                    # hotspot별로 commit
                    # 중간 실패 시 앞 데이터 보존
                    conn.commit()

                success += 1

            except Exception as e:

                conn.rollback()

                failures.append(
                    (
                        code,
                        str(e),
                    )
                )

                print(f"[ERROR] " f"{code} / " f"{db_name}: " f"{e}")

            time.sleep(0.2)

        # ==========================================
        # 결과
        # ==========================================

        print("\n=== 도시데이터 수집 결과 ===")

        print(
            "성공:",
            success,
        )

        print(
            "실패:",
            len(failures),
        )

        if failures:

            print("\n=== 실패 hotspot ===")

            for code, error in failures:
                print(f"{code}: {error}")

        if not args.dry_run:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM hotspot_snapshot
                    """)

                print(
                    "\nhotspot_snapshot 전체:",
                    cur.fetchone()[0],
                )

                cur.execute("""
                    SELECT COUNT(*)
                    FROM hotspot_latest
                    """)

                print(
                    "hotspot_latest 전체:",
                    cur.fetchone()[0],
                )

        if failures:
            raise RuntimeError(f"{len(failures)}개 hotspot " "수집 실패")

    finally:

        conn.close()


if __name__ == "__main__":
    main()
