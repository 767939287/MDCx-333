from pathlib import Path

import pytest

from mdcx.utils.path import safe_rmtree


def test_safe_rmtree_removes_regular_directory(tmp_path: Path):
    target = tmp_path / "remove-me"
    target.mkdir()
    (target / "file.txt").write_text("x")

    safe_rmtree(target)

    assert not target.exists()


def test_safe_rmtree_rejects_empty_path():
    with pytest.raises(ValueError, match="空路径"):
        safe_rmtree("")


def test_safe_rmtree_rejects_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """空路径 / 相对路径经 resolve() 会落到当前工作目录，必须拒绝。

    回归场景：结果树里 file_path 为空的条目走「删除文件夹」时，split_path 得到
    "."，safe_rmtree 曾经会直接 rmtree 掉进程当前目录。
    """
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    with pytest.raises(PermissionError, match="当前工作目录"):
        safe_rmtree(Path("."))

    assert work.exists()


def test_safe_rmtree_rejects_cwd_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    with pytest.raises(PermissionError, match="当前工作目录"):
        safe_rmtree(tmp_path)

    assert tmp_path.exists()


def test_safe_rmtree_allows_subdirectory_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """守卫只拦 cwd 本身与父目录，cwd 下的子目录仍可正常删除。"""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    target = work / "media"
    target.mkdir()

    safe_rmtree(target)

    assert not target.exists()
