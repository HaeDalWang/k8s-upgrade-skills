#!/usr/bin/env python3
"""
validate_recipe.py — recipe.yaml / recipe.md 스키마 검증

Usage:
  python3 scripts/validate_recipe.py recipe.yaml
  python3 scripts/validate_recipe.py recipe.md      # 마크다운 내 YAML 블록도 지원

Exit code:
  0 = 유효
  1 = 검증 실패
"""

import re
import sys
from pathlib import Path

# ── 스키마 정의 ──────────────────────────────────────────────
REQUIRED_FIELDS = {
    "environment": {"type": str, "allowed": ["aws", "on-prem"]},
    "platform":    {"type": str, "allowed": ["eks", "kubespray"]},
    "iac":         {"type": str, "allowed": ["terraform", "none"]},
    "cluster_name": {"type": str},
    "current_version": {"type": str, "pattern": r"^\d+\.\d+$"},
    "target_version":  {"type": str, "pattern": r"^\d+\.\d+$"},
}

OPTIONAL_FIELDS = {
    "output_language": {"type": str, "allowed": ["ko", "en"], "default": "ko"},
    "notes":           {"type": str, "default": ""},
}

# ── 지원 플랫폼 조합 ────────────────────────────────────────
SUPPORTED_COMBOS = [
    ("aws", "eks", "terraform"),
    # ("on-prem", "kubespray", "none"),  # 계획됨
]


# ── YAML 파싱 (PyYAML 없이 순수 파이썬) ─────────────────────
def parse_simple_yaml(text: str) -> dict:
    """
    단순 key: value YAML 파싱.
    PyYAML 의존성 없이 recipe 수준의 flat YAML을 처리한다.
    """
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # key: value 형태만 처리 (빈 값도 허용)
        match = re.match(r'^([a-z_]+)\s*:\s*(.*)$', line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()

            # 빈 값은 빈 문자열로 저장
            if not value:
                result[key] = ""
                continue

            # 따옴표로 감싸진 값은 그대로 추출 (내부 #, : 무시)
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                result[key] = value[1:-1]
                continue

            # 인라인 주석 제거 (따옴표 밖의 # 만)
            in_single = False
            in_double = False
            for i, ch in enumerate(value):
                if ch == '"' and not in_single:
                    in_double = not in_double
                elif ch == "'" and not in_double:
                    in_single = not in_single
                elif ch == '#' and not in_single and not in_double:
                    value = value[:i].strip()
                    break

            # 따옴표 제거 (주석 제거 후 다시 확인)
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            result[key] = value
    return result


def extract_yaml_from_md(text: str) -> str:
    """마크다운 코드블록(```yaml ... ```) 내 YAML 추출."""
    pattern = re.compile(r'```ya?ml\s*\n(.*?)```', re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1)
    # 코드블록 없으면 전체를 YAML로 시도
    return text


def load_recipe(path: str) -> dict:
    """recipe.yaml 또는 recipe.md를 로드하여 dict 반환."""
    content = Path(path).read_text(encoding="utf-8")
    if path.endswith(".md"):
        print(
            "⚠️  [DEPRECATED] recipe.md 형식은 v2에서 제거 예정입니다. "
            "recipe.yaml로 마이그레이션하세요.",
            file=sys.stderr,
        )
        content = extract_yaml_from_md(content)
    return parse_simple_yaml(content)


# ── 검증 로직 ────────────────────────────────────────────────
def validate(recipe: dict) -> list[str]:
    """검증 실패 시 에러 메시지 리스트 반환. 빈 리스트 = 유효."""
    errors: list[str] = []

    # 1. 필수 필드 존재 확인
    for field, schema in REQUIRED_FIELDS.items():
        if field not in recipe or not recipe[field]:
            errors.append(f"필수 필드 누락: '{field}'")
            continue

        value = recipe[field]

        # 타입 확인
        if not isinstance(value, schema["type"]):
            errors.append(
                f"'{field}': 타입 오류 — 기대: {schema['type'].__name__}, "
                f"실제: {type(value).__name__}")
            continue

        # 허용 값 확인
        if "allowed" in schema and value not in schema["allowed"]:
            errors.append(
                f"'{field}': 허용되지 않는 값 '{value}' — "
                f"허용: {schema['allowed']}")

        # 패턴 확인
        if "pattern" in schema and not re.match(schema["pattern"], value):
            errors.append(
                f"'{field}': 형식 오류 '{value}' — "
                f"기대 패턴: {schema['pattern']} (예: \"1.34\")")

    # 2. 버전 제약 검증
    cv = recipe.get("current_version", "")
    tv = recipe.get("target_version", "")
    if cv and tv and re.match(r'^\d+\.\d+$', cv) and re.match(r'^\d+\.\d+$', tv):
        curr_minor = int(cv.split(".")[1])
        targ_minor = int(tv.split(".")[1])
        gap = targ_minor - curr_minor

        if gap == 0:
            errors.append(
                f"current_version과 target_version이 동일 ({cv})")
        elif gap > 1:
            errors.append(
                f"버전 건너뛰기 불가: {cv} → {tv} (gap={gap}). "
                f"마이너 +1만 허용")
        elif gap < 0:
            errors.append(
                f"다운그레이드 불가: {cv} → {tv}")

    # 3. 플랫폼 조합 검증
    env = recipe.get("environment", "")
    plat = recipe.get("platform", "")
    iac = recipe.get("iac", "")
    if env and plat and iac:
        combo = (env, plat, iac)
        if combo not in SUPPORTED_COMBOS:
            supported_str = ", ".join(
                f"({e}, {p}, {i})" for e, p, i in SUPPORTED_COMBOS)
            errors.append(
                f"미지원 조합: ({env}, {plat}, {iac}) — "
                f"지원: {supported_str}")

    # 4. 선택 필드 허용 값 확인
    for field, schema in OPTIONAL_FIELDS.items():
        if field in recipe and recipe[field]:
            value = recipe[field]
            if "allowed" in schema and value not in schema["allowed"]:
                errors.append(
                    f"'{field}': 허용되지 않는 값 '{value}' — "
                    f"허용: {schema['allowed']}")

    return errors


# ── main ─────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/validate_recipe.py <recipe.yaml|recipe.md>",
              file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not Path(path).exists():
        print(f"ERROR: 파일을 찾을 수 없습니다: {path}", file=sys.stderr)
        sys.exit(1)

    recipe = load_recipe(path)

    if not recipe:
        print(f"ERROR: YAML 파싱 실패 — 유효한 key: value 쌍이 없습니다: {path}",
              file=sys.stderr)
        sys.exit(1)

    # 파싱 결과 출력
    print(f"📋 Recipe: {path}")
    for k, v in recipe.items():
        print(f"   {k}: {v}")
    print()

    errors = validate(recipe)

    if errors:
        print(f"❌ 검증 실패 ({len(errors)}개 오류):")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)
    else:
        print("✅ 검증 통과 — recipe가 유효합니다.")

    # AMI 가용성 사전 경고 (aws cli가 있을 때만)
    tv = recipe.get("target_version", "")
    if tv and _check_ami_available(tv) is False:
        print(f"\n⚠️  경고: {tv} AMI가 아직 미출시일 수 있습니다.")
        print("   gate_check.py 실행 시 INF-002에서 CRITICAL FAIL이 발생할 수 있습니다.")
        print("   AWS에서 AMI를 릴리스할 때까지 대기하세요.")

    sys.exit(0)


def _check_ami_available(target_version: str):
    """AMI 가용성 사전 확인. aws cli 없으면 None 반환."""
    import subprocess
    try:
        r = subprocess.run(
            ["aws", "ssm", "get-parameters-by-path",
             "--path",
             f"/aws/service/eks/optimized-ami/{target_version}"
             "/amazon-linux-2023/x86_64/standard",
             "--recursive",
             "--query", "Parameters | length(@)",
             "--output", "text"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
        return count > 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


if __name__ == "__main__":
    main()
