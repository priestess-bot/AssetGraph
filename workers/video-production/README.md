# AssetGraph Kokoro TTS

This isolated worker exposes the pinned Kokoro v1.0 Mandarin voice used by the
commercial-video pipeline. Model files are downloaded into
`.external/models/kokoro` by default and verified against the release SHA-256
before inference. Set `ASSETGRAPH_KOKORO_MODEL_ROOT` to place the model on a
shared or external data volume.

System dependency: `libsndfile1`. The model's Mandarin G2P dependency also uses
the Python packages locked in `uv.lock`.

```bash
cd workers/video-production
uv sync --frozen
uv run assetgraph-kokoro-tts
```

The service listens on `127.0.0.1:8020` by default. `GET /health` does not load
the model; the first `POST /v1/audio/speech` downloads and initializes it. Only
the `zm_yunyang` voice and WAV output are accepted by this Demo service.
