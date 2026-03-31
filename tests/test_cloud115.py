from pathlib import Path

from sync115pan.cloud115 import Cloud115Service


def test_export_relative_paths_strips_selected_root_directory(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["client"] = object()
    service.__dict__["_rate_limit"] = lambda: None

    def fake_export_dir_parse_iter(client, export_file_ids, timeout=0):
        assert export_file_ids == 123
        return iter(
            [
                "/",
                "/test",
                "/test/子目录",
                "/test/文件.txt",
            ]
        )

    service.export_relative_paths.__globals__["export_dir_parse_iter"] = fake_export_dir_parse_iter
    try:
        assert service.export_relative_paths(123, "/test") == {"子目录", "文件.txt"}
    finally:
        from p115client.tool.export_dir import export_dir_parse_iter as real_export_dir_parse_iter

        service.export_relative_paths.__globals__["export_dir_parse_iter"] = real_export_dir_parse_iter


def test_export_relative_paths_supports_multi_level_root(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["client"] = object()
    service.__dict__["_rate_limit"] = lambda: None

    def fake_export_dir_parse_iter(client, export_file_ids, timeout=0):
        assert export_file_ids == 456
        return iter(
            [
                "/",
                "/test",
                "/test/anime",
                "/test/anime/番剧",
                "/test/anime/番剧/子目录",
                "/test/anime/番剧/文件.txt",
            ]
        )

    service.export_relative_paths.__globals__["export_dir_parse_iter"] = fake_export_dir_parse_iter
    try:
        assert service.export_relative_paths(456, "/test/anime/番剧") == {"子目录", "文件.txt"}
    finally:
        from p115client.tool.export_dir import export_dir_parse_iter as real_export_dir_parse_iter

        service.export_relative_paths.__globals__["export_dir_parse_iter"] = real_export_dir_parse_iter


def test_export_relative_paths_supports_export_with_parent_node(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["client"] = object()
    service.__dict__["_rate_limit"] = lambda: None

    def fake_export_dir_parse_iter(client, export_file_ids, timeout=0):
        assert export_file_ids == 457
        return iter(
            [
                "/anime",
                "/anime/番剧",
                "/anime/番剧/子目录",
                "/anime/番剧/文件.txt",
            ]
        )

    service.export_relative_paths.__globals__["export_dir_parse_iter"] = fake_export_dir_parse_iter
    try:
        assert service.export_relative_paths(457, "/test/anime/番剧") == {"子目录", "文件.txt"}
    finally:
        from p115client.tool.export_dir import export_dir_parse_iter as real_export_dir_parse_iter

        service.export_relative_paths.__globals__["export_dir_parse_iter"] = real_export_dir_parse_iter


def test_export_relative_paths_supports_root_directory(tmp_path: Path) -> None:
    service = Cloud115Service("UID=1; CID=2", tmp_path / "cookies.txt")
    service.__dict__["client"] = object()
    service.__dict__["_rate_limit"] = lambda: None

    def fake_export_dir_parse_iter(client, export_file_ids, timeout=0):
        assert export_file_ids == 789
        return iter(
            [
                "/",
                "/a",
                "/a/x.txt",
                "/b",
                "/b/y.txt",
            ]
        )

    service.export_relative_paths.__globals__["export_dir_parse_iter"] = fake_export_dir_parse_iter
    try:
        assert service.export_relative_paths(789, "/") == {"a", "a/x.txt", "b", "b/y.txt"}
    finally:
        from p115client.tool.export_dir import export_dir_parse_iter as real_export_dir_parse_iter

        service.export_relative_paths.__globals__["export_dir_parse_iter"] = real_export_dir_parse_iter
