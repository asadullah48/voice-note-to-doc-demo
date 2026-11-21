import subprocess
import sys
from pathlib import Path

import pytest

from voice_to_doc.cli import main

ROOT = Path(__file__).parents[1]


def test_demo_never_approves_and_refuses_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(['--db', str(tmp_path / 'demo.db'), 'demo', '--out', str(tmp_path / 'out')])
    out = capsys.readouterr().out
    assert out.startswith('SYNTHETIC DATA ONLY')
    assert 'State: flagged' in out
    assert 'Export refused' in out
    assert 'State: approved' not in out
    assert 'python -m voice_to_doc' in out  # the commands a human must run
    assert not (tmp_path / 'out').exists() or not any((tmp_path / 'out').rglob('*.md'))


def test_one_command_demo_runs_as_module(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, '-m', 'voice_to_doc', 'demo'],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    assert 'SYNTHETIC DATA ONLY' in result.stdout and 'Export refused' in result.stdout
    assert (tmp_path / 'voice_to_doc.db').is_file()  # default --db is ./voice_to_doc.db


def test_printed_commands_are_exact_and_persist_across_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import shlex

    db, out = tmp_path / 'demo.db', tmp_path / 'out'
    main(['--db', str(db), 'demo', '--out', str(out)])
    commands = [line.strip() for line in capsys.readouterr().out.splitlines() if line.startswith('  python -m')]
    assert [shlex.split(c)[5] for c in commands] == ['correct', 'approve', 'export']
    for command in commands:  # each is a separate process-like invocation over the same file
        main(shlex.split(command.replace('<your name>', 'SYNTHETIC_REVIEWER'), posix=True)[3:])
    output = capsys.readouterr().out
    assert 'State: approved' in output and 'Exported approved Markdown:' in output
    assert len(list(out.glob('demo-order-*.md'))) == 1
