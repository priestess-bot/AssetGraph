# Qwen3 4B 共享检索服务

该目录随 AssetGraph 分发本地 Qwen3 Embedding/Reranker HTTP 服务源码。模型权重不进入 Git；仓库通过 `reproducibility.lock.json` 固定 Hugging Face 仓库与 revision。

## 前置条件

- Python 3.11
- Hugging Face `hf` CLI
- 约 20 GB 可用磁盘空间
- GPU 可选；CPU 可以启动但推理较慢

## 下载固定版本模型

从仓库根目录执行：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-qwen-models
```

默认下载到：

```text
.external/models/qwen3-4b/Qwen3-Embedding-4B
.external/models/qwen3-4b/Qwen3-Reranker-4B
```

也可通过 `QWEN3_EMBEDDING_PATH` 和 `QWEN3_RERANKER_PATH` 指向共享模型目录。

## 创建服务环境

`services/qwen3/uv.lock` 固定完整传递依赖、平台 artifact 与 SHA-256。Qwen 服务支持 Python `>=3.11,<3.14`，bootstrap 固定用 Python 3.12 复现 CPU/PyPI 的 `torch==2.5.1` 环境：

```bash
cd services/qwen3
uv sync --python 3.12 --frozen
```

`--with-qwen-models` 也会在模型下载完成后执行上述锁定安装。CUDA 主机如需替换 PyTorch 构建，应将其作为明确的本机部署变体，不再声称与默认锁完全一致。

## 启动

```bash
python qwen3_shared_server.py
```

环境变量：

- `QWEN3_MODELS_ROOT`：两个模型目录的父目录
- `QWEN3_EMBEDDING_PATH` / `QWEN3_RERANKER_PATH`：分别覆盖模型路径
- `QWEN3_API_KEY`：默认 `local-no-auth`
- `QWEN3_HOST` / `QWEN3_PORT`：默认 `127.0.0.1:8010`
- `QWEN3_MAX_LENGTH`：默认 4096

验证：

```bash
curl http://127.0.0.1:8010/health
```

服务采用懒加载、单模型驻留：embedding 与 reranker 互斥加载，降低显存占用。
