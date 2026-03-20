# GitHub-Ready Export

This folder is a cleaned source export of `browser-ai-studio` prepared so it can be committed to GitHub without hitting GitHub's 100 MB per-file limit.

## What was intentionally left out

- `build/`
- `dist/`
- `tmp_video_frames/`
- `logs/`
- `output/`
- `data/n8n_runtime/`
- `data/n8n_sidecar/`
- `data/guide_videos/`
- `data/benchmarks/`
- `data/action_evidence/`
- `data/dom_live_learning/`
- `data/worker_learning/`
- `data/worker_learning_smoke/`
- `data/worker_learning_test/`
- `data/worker_sessions/`
- `tools/ffmpeg/`
- generated `__pycache__` folders

## Notes

- Empty folders from the original project are not included unless they had tracked files.
- This export keeps the app source, tests, docs, configs, and lightweight assets.
- The included `.gitignore` is set up to keep regenerated build/runtime files out of Git.
