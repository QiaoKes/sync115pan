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

The service starts on `http://127.0.0.1:38000`.

## Linux NAS Deployment

For a standard Linux NAS with `systemd`, the project can be deployed with one script.

```bash
git clone <your-repo-url>
cd sync115pan
chmod +x scripts/deploy_systemd.sh
sudo ./scripts/deploy_systemd.sh
```

The script will:

- create `.venv/`
- install project dependencies
- create `.data/systemd.env`
- write `/etc/systemd/system/sync115pan.service`
- run `systemctl enable --now sync115pan`

Default runtime values:

- host: `0.0.0.0`
- port: `38000`
- data dir: `<repo>/.data`

Optional environment variables before running the script:

- `PYTHON_BIN`: specific Python interpreter, for example `python3.12`
- `SERVICE_NAME`: custom systemd service name
- `SERVICE_USER`: custom service user
- `SERVICE_GROUP`: custom service group
- `SYNC115PAN_HOST`: bind host
- `SYNC115PAN_PORT`: bind port
- `SYNC115PAN_DATA_DIR`: custom data directory

Useful commands after deployment:

```bash
sudo systemctl status sync115pan
sudo systemctl restart sync115pan
sudo journalctl -u sync115pan -f
```

## Environment Variables

- `SYNC115PAN_DATA_DIR`: custom data directory. Defaults to `.data/` under the repository root.
- `SYNC115PAN_HOST`: bind host, default `127.0.0.1`
- `SYNC115PAN_PORT`: bind port, default `38000`

## Notes

- The project targets Python 3.12+ because `p115client` currently requires it.
- Docker deployments should prefer `watch_mode=auto` or `watch_mode=polling`, which causes `watchfiles` to use polling inside containers.
- Full sync uses the 115 directory export interface and only compares relative paths, reducing directory traversal risk.
