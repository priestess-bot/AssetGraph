# AssetGraph live-research worker

This package isolates two pinned upstream sidecars:

- StreamCap `v1.0.3` at commit `ba9f1e6e6a861ad489e738cf5f5bee491774e972` records one 720p room into 10-minute TS chunks.
- douyinLive `v2.0.24` at commit `79453ece4a440f4439e72d9624e69b0ddbe9c239` supplies live-status and raw interaction events.

Run `init-config`, add any authorized cookie to `runtime/douyinlive-config.yaml`, and keep it at mode `0600`. The worker refuses loose secret permissions. Raw event batches are immutable gzip JSONL files written atomically with mode `0600`; only metadata and checksums are sent to AssetGraph.

The default data root is `/DATA/Downloads/AssetGraph/live-research`. StreamCap conversion and source deletion are disabled. AssetGraph owns normalization, derivatives, and two-phase 30-day retention for raw video chunks. Raw interaction-event batches are retained permanently.

```bash
uv sync --project workers/live-research
uv run --project workers/live-research assetgraph-live-research init-config
uv run --project workers/live-research assetgraph-live-research verify-sidecars
uv run --project workers/live-research assetgraph-live-research scheduler --once
uv run --project workers/live-research assetgraph-live-research retention --once
uv run --project workers/live-research assetgraph-live-research clip-worker --once
uv run --project workers/live-research assetgraph-live-research analysis-worker --once
```

`scheduler` is the complete single-room path. Its default `local` runtime starts the installed pinned StreamCap and douyinLive processes, waits for their loopback ports, watches `${ASSETGRAPH_LIVE_RESEARCH_ROOT}/staging`, opens a capture session when the first TS part starts growing, stores raw events for that same session, finalizes stable TS parts, appends the normalized timeline, and closes the session after media activity stops. `--sidecars compose` performs the same cycle with `compose.sidecars.yml`; `--sidecars external` only probes already managed sidecars and assumes their StreamCap process reloads the recordings configuration.

`frame_sampling` analysis runs require only FFmpeg. ASR and vision runs require `OPENAI_API_KEY` (or `ASSETGRAPH_OPENAI_API_KEY`); template aggregation requires `DEEPSEEK_API_KEY` (or `ASSETGRAPH_DEEPSEEK_API_KEY`). Missing credentials fail the claimed analysis run explicitly and never produce placeholder observations.
