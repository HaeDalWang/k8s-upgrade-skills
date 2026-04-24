"""
tests/test_validate_recipe.py — validate_recipe.py 단위 테스트
"""

import subprocess
import sys
import tempfile
import os

import pytest

import validate_recipe


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _write_recipe(tmp_path, content: str) -> str:
    p = tmp_path / "recipe.yaml"
    p.write_text(content, encoding="utf-8")
    return str(p)


VALID_BASE = """\
environment: aws
platform: eks
iac: terraform
cluster_name: my-cluster
current_version: "1.33"
target_version: "1.34"
"""


# ══════════════════════════════════════════════════════════════
# parse_services_block
# ══════════════════════════════════════════════════════════════

class TestParseServicesBlock:

    def test_no_services_returns_empty(self):
        assert validate_recipe.parse_services_block(VALID_BASE) == []

    def test_single_service_full(self):
        yaml = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: https://api.example.com/health
"""
        services = validate_recipe.parse_services_block(yaml)
        assert len(services) == 1
        assert services[0]["name"] == "my-api"
        assert services[0]["namespace"] == "production"
        assert services[0]["min_endpoints"] == "2"
        assert services[0]["health_check_url"] == "https://api.example.com/health"

    def test_multiple_services(self):
        yaml = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: https://api.example.com/health
  - name: my-worker
    namespace: production
    min_endpoints: 1
"""
        services = validate_recipe.parse_services_block(yaml)
        assert len(services) == 2
        assert services[0]["name"] == "my-api"
        assert services[1]["name"] == "my-worker"
        assert "health_check_url" not in services[1]

    def test_service_without_health_check_url(self):
        yaml = VALID_BASE + """\
services:
  - name: my-worker
    namespace: production
    min_endpoints: 1
"""
        services = validate_recipe.parse_services_block(yaml)
        assert len(services) == 1
        assert services[0].get("health_check_url", "") == ""

    def test_services_block_ends_at_next_top_level_key(self):
        yaml = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
output_language: ko
"""
        services = validate_recipe.parse_services_block(yaml)
        assert len(services) == 1

    def test_inline_comment_stripped(self):
        yaml = VALID_BASE + """\
services:
  - name: my-api  # main api
    namespace: production
    min_endpoints: 2
"""
        services = validate_recipe.parse_services_block(yaml)
        assert services[0]["name"] == "my-api"


# ══════════════════════════════════════════════════════════════
# validate_services
# ══════════════════════════════════════════════════════════════

class TestValidateServices:

    def test_valid_service_full(self):
        services = [{"name": "my-api", "namespace": "prod", "min_endpoints": "2",
                     "health_check_url": "https://api.example.com/health"}]
        assert validate_recipe.validate_services(services) == []

    def test_valid_service_no_health_check(self):
        services = [{"name": "my-worker", "namespace": "prod", "min_endpoints": "1"}]
        assert validate_recipe.validate_services(services) == []

    def test_missing_name(self):
        services = [{"namespace": "prod", "min_endpoints": "2"}]
        errors = validate_recipe.validate_services(services)
        assert any("name" in e for e in errors)

    def test_missing_namespace(self):
        services = [{"name": "my-api", "min_endpoints": "2"}]
        errors = validate_recipe.validate_services(services)
        assert any("namespace" in e for e in errors)

    def test_missing_min_endpoints(self):
        services = [{"name": "my-api", "namespace": "prod"}]
        errors = validate_recipe.validate_services(services)
        assert any("min_endpoints" in e for e in errors)

    def test_min_endpoints_zero_rejected(self):
        services = [{"name": "my-api", "namespace": "prod", "min_endpoints": "0"}]
        errors = validate_recipe.validate_services(services)
        assert any("min_endpoints" in e for e in errors)

    def test_min_endpoints_non_integer_rejected(self):
        services = [{"name": "my-api", "namespace": "prod", "min_endpoints": "abc"}]
        errors = validate_recipe.validate_services(services)
        assert any("min_endpoints" in e for e in errors)

    def test_health_check_url_invalid_scheme(self):
        services = [{"name": "my-api", "namespace": "prod", "min_endpoints": "2",
                     "health_check_url": "ftp://api.example.com/health"}]
        errors = validate_recipe.validate_services(services)
        assert any("health_check_url" in e for e in errors)

    def test_health_check_url_http_accepted(self):
        services = [{"name": "my-api", "namespace": "prod", "min_endpoints": "2",
                     "health_check_url": "http://api.example.com/health"}]
        assert validate_recipe.validate_services(services) == []

    def test_multiple_services_errors_indexed(self):
        services = [
            {"name": "my-api", "namespace": "prod", "min_endpoints": "2"},
            {"namespace": "prod", "min_endpoints": "0"},
        ]
        errors = validate_recipe.validate_services(services)
        assert any("services[1]" in e for e in errors)


# ══════════════════════════════════════════════════════════════
# load_recipe + validate (통합)
# ══════════════════════════════════════════════════════════════

class TestLoadRecipeWithServices:

    def test_valid_recipe_with_services_passes(self, tmp_path):
        content = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: https://api.example.com/health
"""
        path = _write_recipe(tmp_path, content)
        recipe = validate_recipe.load_recipe(path)
        assert "_services" in recipe
        assert len(recipe["_services"]) == 1
        errors = validate_recipe.validate(recipe)
        assert errors == []

    def test_recipe_without_services_passes(self, tmp_path):
        path = _write_recipe(tmp_path, VALID_BASE)
        recipe = validate_recipe.load_recipe(path)
        assert recipe.get("_services", []) == []
        assert validate_recipe.validate(recipe) == []

    def test_invalid_service_propagates_error(self, tmp_path):
        content = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 0
"""
        path = _write_recipe(tmp_path, content)
        recipe = validate_recipe.load_recipe(path)
        errors = validate_recipe.validate(recipe)
        assert any("min_endpoints" in e for e in errors)


# ══════════════════════════════════════════════════════════════
# CLI 통합 테스트
# ══════════════════════════════════════════════════════════════

class TestCLIWithServices:

    def test_cli_valid_recipe_with_services_exits_0(self, tmp_path):
        content = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: https://api.example.com/health
"""
        path = _write_recipe(tmp_path, content)
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/validate_recipe.py", path],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert "services" in r.stdout

    def test_cli_bestefffort_mode_shown(self, tmp_path):
        content = VALID_BASE + """\
services:
  - name: my-worker
    namespace: production
    min_endpoints: 1
"""
        path = _write_recipe(tmp_path, content)
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/validate_recipe.py", path],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert "BestEffort" in r.stdout

    def test_cli_invalid_service_exits_1(self, tmp_path):
        content = VALID_BASE + """\
services:
  - name: my-api
    namespace: production
    min_endpoints: 0
"""
        path = _write_recipe(tmp_path, content)
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/validate_recipe.py", path],
            capture_output=True, text=True
        )
        assert r.returncode == 1
