"""openapi.yaml → roleC/lib/api-types.ts 생성기.

왜 필요한가
-----------
`roleC/lib/types.ts`는 지금까지 **손으로 베껴 쓴** 계약이었다. 그래서 조용히
어긋난다 — 2026-08-28 실측으로 이런 것들이 나왔다.

  · `POST /api/feedback` 이 422로 전부 실패 (clicked를 boolean으로 보냈다)
  · `GET /api/context/now` 가 필수 쿼리 lat/lng를 안 붙인다
  · `low_confidence` · `radius_expanded` · `image_url` · `rain_prob` 누락

셋 다 **화면은 멀쩡하고 기능만 사라지는** 형태다. 사람이 두 파일을 대조해
막을 수 있는 종류가 아니다. 그래서 계약을 한쪽에서 생성한다.

  openapi.yaml  ──(이 스크립트)──▶  roleC/lib/api-types.ts

`tests/test_ts_contract.py`가 생성 결과와 커밋된 파일을 대조한다. openapi를
고치고 이 스크립트를 안 돌리면 **CI가 막는다.**

사용
----
    cd roleB && python -m tools.gen_ts_types          # 생성
    cd roleB && python -m tools.gen_ts_types --check  # 대조만 (CI용)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "roleB" / "openapi.yaml"
TARGET = ROOT / "roleC" / "lib" / "api-types.ts"

HEADER = """// lib/api-types.ts
//
// ⚠️ 생성 파일이다. 손으로 고치지 말 것 — 다음 생성에서 덮어써진다.
//
//   원본:  roleB/openapi.yaml
//   생성:  cd roleB && python -m tools.gen_ts_types
//   검증:  roleB/tests/test_ts_contract.py (CI에서 돈다)
//
// 계약을 손으로 베껴 쓰다가 POST /api/feedback 이 통째로 422가 난 적이 있다.
// 화면은 멀쩡했고 recommendation_log만 비어 있었다. 그래서 생성으로 바꿨다.
"""


# TS 전역 이름과 부딪히는 스키마명은 바꿔서 내보낸다.
# `Error`를 그대로 쓰면 `class ApiError extends Error`가 자기 자신을 상속한다.
RENAME: dict[str, str] = {"Error": "ApiErrorBody"}


def _name(schema_name: str) -> str:
    return RENAME.get(schema_name, schema_name)


def _lit(value: Any) -> str:
    """enum 값 하나 → TS 리터럴."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"{}"'.format(str(value).replace('"', '\\"'))


def _union(parts: list[str]) -> str:
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " | ".join(seen) if seen else "unknown"


def ts_type(node: Any) -> str:
    """OpenAPI 스키마 노드 → TS 타입 표현."""
    if not isinstance(node, dict):
        return "unknown"

    if "$ref" in node:
        return _name(node["$ref"].rsplit("/", 1)[-1])

    if "oneOf" in node:
        return _union([ts_type(x) for x in node["oneOf"]])
    if "anyOf" in node:
        return _union([ts_type(x) for x in node["anyOf"]])

    raw = node.get("type")
    types = raw if isinstance(raw, list) else ([raw] if raw else [])
    enum = node.get("enum")

    parts: list[str] = []
    for t in types:
        if t == "null":
            parts.append("null")
        elif t == "string":
            if enum:
                parts.extend(_lit(v) for v in enum if v is not None)
                if any(v is None for v in enum):
                    parts.append("null")
            else:
                parts.append("string")
        elif t in ("integer", "number"):
            parts.extend(_lit(v) for v in enum) if enum else parts.append("number")
        elif t == "boolean":
            parts.append("boolean")
        elif t == "array":
            inner = ts_type(node.get("items", {}))
            parts.append(f"({inner})[]" if "|" in inner else f"{inner}[]")
        elif t == "object":
            if node.get("properties"):
                parts.append(_inline_object(node))
            else:
                parts.append("Record<string, unknown>")
        else:
            parts.append("unknown")

    if not parts and enum:
        parts.extend(_lit(v) for v in enum)

    return _union(parts)


def _inline_object(node: dict[str, Any]) -> str:
    required = set(node.get("required", []))
    fields = [
        "{}{}: {}".format(name, "" if name in required else "?", ts_type(spec))
        for name, spec in (node.get("properties") or {}).items()
    ]
    return "{ " + "; ".join(fields) + " }"


def _doc(text: str | None, indent: str = "") -> list[str]:
    """description → JSDoc 블록. 없으면 빈 리스트."""
    if not text:
        return []
    lines = [ln.rstrip() for ln in str(text).strip().splitlines()]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    out = [f"{indent}/**"]
    out.extend(f"{indent} * {ln}".rstrip() for ln in lines)
    out.append(f"{indent} */")
    return out


def render_schema(name: str, node: dict[str, Any]) -> str:
    name = _name(name)
    out: list[str] = []
    out.extend(_doc(node.get("description")))

    raw = node.get("type")
    types = raw if isinstance(raw, list) else ([raw] if raw else [])

    if "object" in types and node.get("properties"):
        required = set(node.get("required", []))
        out.append(f"export interface {name} {{")
        for prop, spec in node["properties"].items():
            doc = _doc(spec.get("description") if isinstance(spec, dict) else None, "  ")
            out.extend(doc)
            opt = "" if prop in required else "?"
            out.append(f"  {prop}{opt}: {ts_type(spec)};")
        out.append("}")
    else:
        out.append(f"export type {name} = {ts_type(node)};")

    return "\n".join(out)


def generate() -> str:
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    schemas: dict[str, Any] = spec["components"]["schemas"]

    blocks = [HEADER.rstrip()]
    for name, node in schemas.items():
        blocks.append(render_schema(name, node))
    return "\n\n".join(blocks) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="쓰지 않고 대조만 한다")
    args = parser.parse_args()

    generated = generate()

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") == generated:
            print(f"OK: {TARGET.relative_to(ROOT)} == openapi.yaml")
            return 0
        print(
            f"DRIFT — {TARGET.relative_to(ROOT)} 가 openapi.yaml 과 다르다.\n"
            "  cd roleB && python -m tools.gen_ts_types",
            file=sys.stderr,
        )
        return 1

    TARGET.write_text(generated, encoding="utf-8", newline="\n")
    print(f"written: {TARGET.relative_to(ROOT)} ({len(generated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
