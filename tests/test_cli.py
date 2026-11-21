import subprocess
import sys
from pathlib import Path

import pytest

from voice_to_doc.cli import main

ROOT = Path(__file__).parents[1]


def test_demo_never_approves_and_refuses_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(['demo', '--out', str(tmp_path / 'out')])
    out = capsys.readouterr().out
    assert out.startswith('SYNTHETIC DATA ONLY')
    assert 'State: flagged' in out
    assert 'Export refused' in out
    assert 'State: approved' not in out
    assert 'python -m voice_to_doc' in out  # the commands a human must run
    assert not (tmp_path / 'out').exists() or not any((tmp_path / 'out').rglob('*.md'))


def test_one_command_demo_runs_as_module(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, '-m', 'voice_to_doc', 'demo', '--out', str(tmp_path / 'out')],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    assert 'SYNTHETIC DATA ONLY' in result.stdout and 'Export refused' in result.stdout
