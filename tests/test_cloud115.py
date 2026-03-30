from pathlib import Path

from sync115pan.cloud115 import Cloud115Service


def test_export_tree_uses_relative_paths(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["_api"] = {
        "export_dir_parse_iter": lambda client, export_file_ids, timeout=0: iter(
            [
                "/测试目录",
                "/测试目录/子目录",
                "/测试目录/子目录/文件.txt",
            ]
        )
    }
    service.__dict__["client"] = object()

    rows = service.export_tree(123)

    assert [row.relative_path for row in rows] == ["子目录", "子目录/文件.txt"]
    assert all(row.remote_id == 0 for row in rows)


def test_export_tree_strips_selected_root_directory(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["_api"] = {
        "export_dir_parse_iter": lambda client, export_file_ids, timeout=0: iter(
            [
                "/",
                "/test",
                "/test/子目录",
                "/test/文件.txt",
            ]
        )
    }
    service.__dict__["client"] = object()

    rows = service.export_tree(123)

    assert [row.relative_path for row in rows] == ["子目录", "文件.txt"]
