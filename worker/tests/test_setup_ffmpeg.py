from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import setup_ffmpeg


def test_setup_local_bin_path_prepends_when_missing(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(setup_ffmpeg, "_bin_dir", lambda: bin_dir)
    monkeypatch.setenv("PATH", "/usr/bin")

    setup_ffmpeg._setup_local_bin_path()

    path = os.environ["PATH"]
    assert path.startswith(str(bin_dir))
    assert "/usr/bin" in path


def test_setup_local_bin_path_noop_when_dir_missing(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(setup_ffmpeg, "_bin_dir", lambda: bin_dir)
    monkeypatch.setenv("PATH", "/usr/bin")

    setup_ffmpeg._setup_local_bin_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_setup_local_bin_path_noop_when_already_present(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(setup_ffmpeg, "_bin_dir", lambda: bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin")

    setup_ffmpeg._setup_local_bin_path()

    assert os.environ["PATH"] == f"{bin_dir}{os.pathsep}/usr/bin"


def test_ffmpeg_ready_false_when_missing(monkeypatch):
    monkeypatch.setattr(setup_ffmpeg.shutil, "which", lambda _: None)

    assert setup_ffmpeg._ffmpeg_ready() is False


def test_ffmpeg_ready_true_when_operational(monkeypatch):
    monkeypatch.setattr(setup_ffmpeg.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(setup_ffmpeg, "_binary_operational", lambda _: True)

    assert setup_ffmpeg._ffmpeg_ready() is True


def test_ffmpeg_ready_false_when_binary_fails(monkeypatch):
    monkeypatch.setattr(setup_ffmpeg.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(setup_ffmpeg, "_binary_operational", lambda _: False)

    assert setup_ffmpeg._ffmpeg_ready() is False


def test_ensure_ffmpeg_short_circuits_when_ready(monkeypatch):
    setup_called = MagicMock()
    monkeypatch.setattr(setup_ffmpeg, "_setup_local_bin_path", setup_called)
    monkeypatch.setattr(setup_ffmpeg, "_ffmpeg_ready", lambda: True)
    monkeypatch.setattr(setup_ffmpeg, "_install_ffmpeg", lambda _: False)

    setup_ffmpeg.ensure_ffmpeg()

    assert setup_called.called


def test_install_ffmpeg_returns_false_on_darwin(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_ffmpeg.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup_ffmpeg.platform, "machine", lambda: "arm64")

    assert setup_ffmpeg._install_ffmpeg(Path(tmp_path)) is False
