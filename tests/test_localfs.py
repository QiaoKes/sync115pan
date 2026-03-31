from pathlib import Path

from sync115pan.localfs import dedupe_scopes, to_local_path, walk_local_tree


def test_walk_local_tree_collects_files_and_dirs(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "nested.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "root.txt").write_text("world", encoding="utf-8")

    rows = walk_local_tree(tmp_path)
    paths = {row["relative_path"] for row in rows}

    assert "alpha" in paths
    assert "alpha/nested.txt" in paths
    assert "root.txt" in paths


def test_dedupe_scopes_returns_parent_directories(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a" / "y.txt").write_text("y", encoding="utf-8")

    scopes = dedupe_scopes(
        tmp_path,
        [
            str(tmp_path / "a" / "x.txt"),
            str(tmp_path / "a" / "y.txt"),
        ],
    )
    assert scopes == ["a"]


def test_to_local_path_rebuilds_local_path_from_posix_relative(tmp_path: Path) -> None:
    resolved = to_local_path("番剧/T/01.mp4", tmp_path)

    assert resolved == tmp_path.resolve() / "番剧" / "T" / "01.mp4"
