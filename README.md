# TaskTrail

Reconstructed from the portfolio description of a Flask/SQLite email-to-task tracker. This clean-room prototype uses Python's standard-library HTTP server and SQLite, rather than Flask; it is not recovered original source or a copy of the hosted service.

## Run

Requires Python 3.10+. Run `python3 tasktrail.py`; open `http://127.0.0.1:8000`. Submit email text in the page or `POST /api/runs` with `{"email":"..."}`. Run state and task results persist in SQLite. `GET /api/runs/<id>` returns a run and its tasks.

The pipeline checkpoints each of six stages, retries transient failures, deduplicates repeated submissions by content hash, recovers queued/running work on server startup, and uses a uniqueness constraint for tasks. `GET /api/runs/<id>/events` streams persisted stage/retry events as server-sent events. Task extraction is intentionally transparent keyword/line matching; it does not claim general NLP accuracy. The original portfolio's 9/9 sample result is a historical claim and is not claimed for this reconstruction.

## Verify

`python3 -m unittest -v`

No external service is called. Set `--db PATH` to choose a local database.
