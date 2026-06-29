import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "nightly_git_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("nightly_git_checkpoint", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_write_gate_requires_flag_and_environment():
    assert MODULE.writes_allowed(execute=False, environment={"NIGHTLY_GIT_ALLOW_WRITE": "1"}) is False
    assert MODULE.writes_allowed(execute=True, environment={}) is False
    assert MODULE.writes_allowed(execute=True, environment={"NIGHTLY_GIT_ALLOW_WRITE": "1"}) is True


def test_secret_scan_detects_tokens_without_exposing_values(tmp_path):
    (tmp_path / "safe.txt").write_text("TG_COMPANION_BOT_TOKEN=", encoding="utf-8")
    fake_token = "1234567890:" + "A" * 33
    (tmp_path / "leak.txt").write_text(f"token={fake_token}", encoding="utf-8")

    issues = MODULE.scan_secret_issues(tmp_path, ["safe.txt", "leak.txt"])

    assert issues == [{"path": "leak.txt", "reason": "telegram_token"}]
    assert "1234567890" not in str(issues)


def test_secret_scan_blocks_secret_filenames_even_when_empty(tmp_path):
    (tmp_path / ".env").write_text("", encoding="utf-8")

    issues = MODULE.scan_secret_issues(tmp_path, [".env"])

    assert issues == [{"path": ".env", "reason": "forbidden_secret_filename"}]


def test_script_defaults_to_dry_run_mode():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'parser.add_argument("--execute", action="store_true"' in source
    assert "NIGHTLY_GIT_ALLOW_WRITE" in source


def test_scheduler_wrapper_uses_the_gated_checkpoint_entrypoint():
    wrapper = PROJECT_ROOT / "scripts" / "run_nightly_git_checkpoint.ps1"
    source = wrapper.read_text(encoding="utf-8")

    assert '$env:NIGHTLY_GIT_ALLOW_WRITE = "1"' in source
    assert "nightly_git_checkpoint.py" in source
    assert "--execute" in source
