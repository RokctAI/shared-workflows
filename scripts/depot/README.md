# depot jobs

Repo-side jobs for [depot_sdk](https://github.com/RokctAI/hardware/tree/main/depot)
storage repos: the private repos where the photos and drive apps keep a
user's files. They run in **the user's** repo, on **the user's** Actions
minutes, through `.github/workflows/universal-depot.yml`, called from the one
caller file the app installs there (`examples/depot/depot.yml`).

The only credential is that run's `GITHUB_TOKEN`, which reaches the repo the
job runs in and nothing else. Anything that crosses repos (creating the next
shard, handing a job over) is done by the app (`depot/CONTRACT.md`, "the app
carries everything between repos").

## Jobs

| Command | What it does | Stops with |
|---|---|---|
| `size` | Writes `depot/size.json` from GitHub's packed repo size; skips the commit when nothing meaningful moved | – |
| `import` | Imports the items the user picked in the Google Photos Picker, page by page: objects, thumbnails, index entries | `done`, `running` (time budget), `needs_token`, `repo_full`, `failed` |
| `exif` | Date taken, GPS and camera into `depot/meta/` and the entry tags; dates undated photos | `done`, `running` |
| `people` | Finds faces (YuNet) and matches them (SFace) to `depot/people/registry.json`; writes `depot/people/faces/` and the `people` tag | `done`, `running` |

The workflow's `maintain` job runs `size`, `exif` and `people` in one runner.

## Resumable by design

- Every chunk is one commit: objects, index shards, manifest and the job note
  `depot/jobs/<job>.json` together. A run that stops for any reason (time
  budget, token expiry, a full repo, Actions minutes running out) loses at
  most the chunk in flight, and redoing it is harmless (objects are
  content-addressed; enrich jobs skip entries already tagged).
- Commits race with the phone, which writes through the GitHub API. A rejected
  push re-applies the chunk on top of the fresh head (`gitops.commit_batch`).
- The checkout is sparse (`depot/index`, `depot/jobs`, `depot/people`) and
  blobless, so a 9 GB repo is never downloaded; objects are fetched one at a
  time when a job reads them.

## Google Photos

Google removed full-library read access from the Photos Library API on
2025-03-31. The app runs the **Picker** on the phone; the user selects
photos or albums; the app dispatches `import` with the picker session id and
a short-lived token (scope `photospicker.mediaitems.readonly`). The token is
masked in the logs and is useless after about an hour; when it expires the
job stops with `needs_token` and the app re-dispatches it with a fresh one.

## Face models

From [opencv_zoo](https://github.com/opencv/opencv_zoo), pinned by commit and
SHA-256 in `people_job.py`, downloaded at run time:

- YuNet `face_detection_yunet_2023mar.onnx`, MIT
- SFace `face_recognition_sface_2021dec.onnx`, Apache-2.0, 128-d embeddings,
  cosine threshold 0.363

InsightFace's pretrained models are licensed for non-commercial research
only, so they are not used. The phone must use the same SFace model for
faces it finds on-device, or the embeddings are not comparable.

## Tests

```sh
python3 scripts/tests/test_depot_jobs.py
```

The tests use a real bare git repo as the remote and fake the Picker API and
the face engine.
