import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

SEOUL_API_KEY = os.getenv("SEOUL_API_KEY")

BASE_URL = "http://openapi.seoul.go.kr:8088"

TEST_AREA_CODE = "POI004"


def main():

    if not SEOUL_API_KEY:
        raise ValueError("SEOUL_API_KEY가 .env에 없습니다.")

    url = (
        f"{BASE_URL}/"
        f"{SEOUL_API_KEY}/"
        f"json/"
        f"citydata/"
        f"1/5/"
        f"{TEST_AREA_CODE}"
    )

    response = requests.get(
        url,
        timeout=30,
    )

    print(
        "HTTP:",
        response.status_code,
    )

    response.raise_for_status()

    data = response.json()

    # 키가 포함된 URL은 출력하지 않는다.
    print("\n=== 최상위 key ===")

    print(list(data.keys()))

    print("\n=== 응답 앞부분 ===")

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )[:3000]
    )

    service = data.get("CITYDATA")

    print("\n=== RESULT ===")

    print(data.get("RESULT"))

    if not service:
        print("CITYDATA가 없습니다.")
        return

    row = service

    print("\n=== 장소 ===")

    print(
        "AREA_CD:",
        row.get("AREA_CD"),
    )

    print(
        "AREA_NM:",
        row.get("AREA_NM"),
    )

    print("\n=== row key ===")

    print(list(row.keys()))

    # ------------------------------------------
    # 실시간 인구
    # ------------------------------------------

    ppltn = row.get(
        "LIVE_PPLTN_STTS",
        [],
    )

    print(
        "\nLIVE_PPLTN_STTS 타입:",
        type(ppltn).__name__,
    )

    print(
        "LIVE_PPLTN_STTS 개수:",
        len(ppltn) if isinstance(ppltn, list) else "-",
    )

    if isinstance(ppltn, list) and ppltn:

        print("\n=== 인구 key ===")

        print(list(ppltn[0].keys()))

        print("\n=== 인구 샘플 ===")

        print(
            json.dumps(
                ppltn[0],
                ensure_ascii=False,
                indent=2,
            )[:6000]
        )

    # ------------------------------------------
    # 날씨
    # ------------------------------------------

    weather = row.get(
        "WEATHER_STTS",
        [],
    )

    print(
        "\nWEATHER_STTS 타입:",
        type(weather).__name__,
    )

    print(
        "WEATHER_STTS 개수:",
        len(weather) if isinstance(weather, list) else "-",
    )

    if isinstance(weather, list) and weather:

        print("\n=== 날씨 key ===")

        print(list(weather[0].keys()))

        print("\n=== 날씨 샘플 ===")

        print(
            json.dumps(
                weather[0],
                ensure_ascii=False,
                indent=2,
            )[:6000]
        )

    print("\n=== CITYDATA key ===")

    print(list(row.keys()))

    weather = row.get("WEATHER_STTS", [])

    print(
        "\nWEATHER_STTS 타입:",
        type(weather).__name__,
    )

    print(
        "WEATHER_STTS 개수:",
        len(weather) if isinstance(weather, list) else "-",
    )

    if isinstance(weather, list) and weather:

        print("\n=== 날씨 key ===")

        print(list(weather[0].keys()))

        print("\n=== 날씨 샘플 ===")

        print(
            json.dumps(
                weather[0],
                ensure_ascii=False,
                indent=2,
            )[:5000]
        )


if __name__ == "__main__":
    main()
