# sync115pan

`sync115pan` is a Python 3.12+ service for syncing a single local directory into a single 115 cloud directory.

Current capabilities:

- Full sync: scan local tree, export cloud tree, create missing directories, upload missing files.
- Incremental sync: watch a local directory with `watchfiles`, coalesce changes by directory, and sync only affected scopes.
- File-backed state: `config.json`, `retry_state.json`, and `app.log`.
- Web UI and JSON API for cookie, single sync config, manual full sync, logs, and runtime status.

## Requirements

- Python 3.12+
- A valid 115 cookie string

`p115client` is installed directly from GitHub because it is not published on PyPI in the form used by this project.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
sync115pan
```

The service starts on `http://127.0.0.1:8000`.

## Environment Variables

- `SYNC115PAN_DATA_DIR`: custom data directory. Defaults to `.data/` under the repository root.
- `SYNC115PAN_HOST`: bind host, default `127.0.0.1`
- `SYNC115PAN_PORT`: bind port, default `8000`

## Notes

- The project targets Python 3.12+ because `p115client` currently requires it.
- Docker deployments should prefer `watch_mode=auto` or `watch_mode=polling`, which causes `watchfiles` to use polling inside containers.
- Full sync uses the 115 directory export interface and only compares relative paths, reducing directory traversal risk.
