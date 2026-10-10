"""Generate the web app's workflow TypeScript types from the workflow JSON Schema.

The schema is the one source of truth. This handles the subset of JSON Schema the
workflow schema uses: objects, arrays, strings, integers, enums, and local $refs.
tests/tooling/test_workflow_types.py fails when the checked-in output drifts.

    python scripts/gen_workflow_types.py            # rewrite apps/web/src/workflow.gen.ts
    python scripts/gen_workflow_types.py --stdout   # print instead
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "apps/engine/ace_engine/workflow.schema.json"
OUTPUT = ROOT / "apps/web/src/workflow.gen.ts"
HEADER = (
    "// Generated from apps/engine/ace_engine/workflow.schema.json by\n"
    "// scripts/gen_workflow_types.py. Do not edit: run `make types`.\n"
)
REF_PREFIX = "#/$defs/"
PRIMITIVES = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}


class UnsupportedSchema(ValueError):
    pass


def _doc(node: dict[str, Any], indent: str = "") -> str:
    text = node.get("description")
    return f"{indent}/** {text} */\n" if text else ""


def _type_of(node: dict[str, Any]) -> str:
    if "$ref" in node:
        ref: str = node["$ref"]
        if not ref.startswith(REF_PREFIX):
            raise UnsupportedSchema(f"only local $refs are supported: {ref}")
        return ref[len(REF_PREFIX) :]
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])
    kind = node.get("type")
    if kind == "array":
        return f"{_type_of(node['items'])}[]"
    if kind in PRIMITIVES:
        return PRIMITIVES[kind]
    raise UnsupportedSchema(f"unsupported schema node: {json.dumps(node)[:120]}")


def _interface(name: str, node: dict[str, Any]) -> str:
    required = set(node.get("required", []))
    fields = []
    for field, spec in node.get("properties", {}).items():
        optional = "" if field in required else "?"
        fields.append(f"{_doc(spec, '  ')}  {field}{optional}: {_type_of(spec)};\n")
    return f"{_doc(node)}export interface {name} {{\n{''.join(fields)}}}\n"


def _declaration(name: str, node: dict[str, Any]) -> str:
    if node.get("type") == "object":
        return _interface(name, node)
    if "enum" in node:
        values = ", ".join(json.dumps(v) for v in node["enum"])
        return (
            f"export const {name}Values = [{values}] as const;\n"
            f"{_doc(node)}export type {name} = (typeof {name}Values)[number];\n"
        )
    return f"{_doc(node)}export type {name} = {_type_of(node)};\n"


def render(schema: dict[str, Any]) -> str:
    parts = [HEADER]
    parts += [_declaration(name, node) for name, node in schema.get("$defs", {}).items()]
    parts.append(_declaration(schema["title"], schema))
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args()
    output = render(json.loads(args.schema.read_text()))
    if args.stdout:
        sys.stdout.write(output)
    else:
        OUTPUT.write_text(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
