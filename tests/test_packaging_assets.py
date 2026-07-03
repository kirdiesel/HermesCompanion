from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_src_package_without_runtime_framework_dependencies() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "tg-companion-bot"
    assert data["project"]["requires-python"] == ">=3.11"
    assert data["project"]["dependencies"] == []
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert "wheel" in data["build-system"]["requires"]

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.sqlite3" in gitignore
    assert "*.sqlite3-wal" in gitignore
    assert "*.sqlite3-shm" in gitignore
