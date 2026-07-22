from __future__ import annotations

import os
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "creative" / "jd-wine-livestream-scriptwriting"


def test_jd_wine_script_skill_is_bundled_and_self_contained() -> None:
    skill_path = SKILL_ROOT / "SKILL.md"
    assert skill_path.is_file(), "剧本 Skill 必须随仓库分发"

    content = skill_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "name: jd-wine-livestream-scriptwriting" in content
    assert len(content) <= 100_000

    linked_paths = re.findall(r"\]\((references/[^)]+|templates/[^)]+)\)", content)
    assert linked_paths, "Skill 必须显式链接必要参考和模板"
    assert all((SKILL_ROOT / relative).is_file() for relative in linked_paths)

    required = {
        "references/independent-transition-video-scenes.md",
        "references/long-loop-editorial-audit.md",
        "references/quality-baseline.md",
        "templates/product-fact-card.yaml",
    }
    assert required.issubset(set(linked_paths) | {p.as_posix().split("jd-wine-livestream-scriptwriting/", 1)[-1] for p in SKILL_ROOT.rglob("*") if p.is_file()})


def test_reproducibility_entrypoints_are_committed() -> None:
    required_paths = [
        "reproducibility.lock.json",
        "scripts/bootstrap_reproducible.py",
        "scripts/apply_migrations.py",
        "scripts/verify_reproducibility.py",
        ".github/workflows/reproducibility.yml",
        "services/qwen3/pyproject.toml",
        "services/qwen3/uv.lock",
        "services/qwen3/README.md",
        "workers/video-production/pyproject.toml",
        "workers/video-production/uv.lock",
        "workers/video-production/README.md",
        "workers/live-research/pyproject.toml",
        "workers/live-research/uv.lock",
        "workers/live-research/README.md",
        "workers/live-research/streamcap-requirements.lock.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
    ]
    missing = [relative for relative in required_paths if not (REPO_ROOT / relative).is_file()]
    assert missing == []


def test_default_env_file_respects_explicit_test_isolation() -> None:
    from app.core.config import DEFAULT_ENV_FILE

    expected = Path(os.environ.get("ASSETGRAPH_ENV_FILE", REPO_ROOT / ".env")).resolve()
    assert DEFAULT_ENV_FILE == expected


def test_python_support_range_matches_reproducibility_contract() -> None:
    for relative in (
        "backend/pyproject.toml",
        "workers/browser-use/pyproject.toml",
        "workers/live-research/pyproject.toml",
    ):
        content = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert 'requires-python = ">=3.11,<3.15"' in content
    qwen_content = (REPO_ROOT / "services/qwen3/pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11,<3.14"' in qwen_content
    video_tts_content = (REPO_ROOT / "workers/video-production/pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12,<3.13"' in video_tts_content


def test_backend_dev_dependency_includes_starlette_httpx2_adapter() -> None:
    pyproject = (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"httpx2>=2.5.0"' in pyproject
    assert '"httpx>=0.28.0"' in pyproject
