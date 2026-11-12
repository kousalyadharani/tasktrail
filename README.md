# TaskTrail

Reconstructed from the portfolio description of a Flask/SQLite email-to-task tracker. This is a clean-room, local prototype, not recovered original source or a copy of the hosted service.

## Run

Requires Python 3.10+. Run `python3 tasktrail.py`; open `http://127.0.0.1:8000`. Submit email text in the page or `POST /api/runs` with `{"email":"..."}`. Run state and task results persist in SQLite. `GET /api/runs/<id>` returns a run and its tasks.

The pipeline checkpoints each of six stages, retries transient failures, deduplicates repeated submissions by content hash, and uses a uniqueness constraint for tasks. Task extraction is intentionally transparent keyword/line matching; it does not claim general NLP accuracy. The original portfolio describes richer email parsing, server-sent event visualizations, restart recovery, and 9/9 sample extraction. Those original test results are historical claims and are not claimed for this reconstruction.

## Verify

`python3 -m unittest -v`

No external service is called. Set `--db PATH` to choose a local database.
