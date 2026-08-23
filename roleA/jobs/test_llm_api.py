import os
import json
import requests

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")
MODEL = os.getenv("LLM_MODEL")


def main():
    url = f"{BASE_URL.rstrip('/')}/chat/completions/"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    schema = {
        "type": "object",
        "properties": {
            "noise_level": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 5,
            }
        },
        "required": ["noise_level"],
        "additionalProperties": False,
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "장소 리뷰에서 속성을 추출하세요.",
            },
            {
                "role": "user",
                "content": "리뷰: 조용하고 대화하기 좋은 카페였습니다.",
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "poi_attributes",
                "strict": True,
                "schema": schema,
            },
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=60,
    )

    print("status:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return

    data = response.json()

    content = data["choices"][0]["message"]["content"]

    print("raw:", content)
    print("parsed:", json.loads(content))


if __name__ == "__main__":
    main()
