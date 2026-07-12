from __future__ import annotations

import argparse
import gc
import os
import threading
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get("QWEN3_MODELS_ROOT", REPO_ROOT / ".external" / "models" / "qwen3-4b"))
DEFAULT_EMBEDDING_PATH = DEFAULT_ROOT / "Qwen3-Embedding-4B"
DEFAULT_RERANKER_PATH = DEFAULT_ROOT / "Qwen3-Reranker-4B"
DEFAULT_API_KEY = os.environ.get("QWEN3_API_KEY", "local-no-auth")
DEFAULT_TASK = os.environ.get(
    "QWEN3_RETRIEVAL_TASK",
    "Given a web search query, retrieve relevant passages that answer the query",
)


def now_ms() -> int:
    return int(time.time() * 1000)


def cuda_available() -> bool:
    return torch.cuda.is_available()


def preferred_dtype() -> torch.dtype:
    if cuda_available():
        # Qwen configs are bf16; RTX 40 supports bf16, but fp16 is often safer across Windows builds.
        return torch.float16
    return torch.float32


def device_name() -> str:
    if cuda_available():
        return torch.cuda.get_device_name(0)
    return "cpu"


def clear_torch_memory() -> None:
    gc.collect()
    if cuda_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


def detailed_query(task: str, query: str) -> str:
    return f"Instruct: {task}\nQuery:{query}"


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    dimensions: int | None = Field(default=None, ge=32, le=2560)
    encoding_format: str | None = "float"
    instruction: str | None = None
    is_query: bool = False


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model: str | None = None
    top_n: int | None = Field(default=None, ge=1)
    return_documents: bool = True
    instruction: str | None = None
    max_length: int | None = Field(default=None, ge=128, le=32768)


class ModelManager:
    def __init__(self, embedding_path: Path, reranker_path: Path, max_length: int, api_key: str) -> None:
        self.embedding_path = embedding_path
        self.reranker_path = reranker_path
        self.max_length = max_length
        self.api_key = api_key
        self.lock = threading.RLock()
        self.active = "none"
        self.embedding_tokenizer = None
        self.embedding_model = None
        self.rerank_tokenizer = None
        self.rerank_model = None
        self.rerank_true_id = None
        self.rerank_false_id = None
        self.rerank_prefix_tokens = None
        self.rerank_suffix_tokens = None

    def check_auth(self, authorization: str | None) -> None:
        if not self.api_key:
            return
        if authorization == f"Bearer {self.api_key}":
            return
        raise HTTPException(status_code=401, detail={"message": "unauthorized", "type": "auth_error"})

    def unload_all(self) -> None:
        self.embedding_tokenizer = None
        self.embedding_model = None
        self.rerank_tokenizer = None
        self.rerank_model = None
        self.rerank_true_id = None
        self.rerank_false_id = None
        self.rerank_prefix_tokens = None
        self.rerank_suffix_tokens = None
        self.active = "none"
        clear_torch_memory()

    def ensure_embedding(self) -> None:
        with self.lock:
            if self.active == "embedding" and self.embedding_model is not None:
                return
            self.unload_all()
            kwargs: dict[str, Any] = {"torch_dtype": preferred_dtype()} if cuda_available() else {}
            self.embedding_tokenizer = AutoTokenizer.from_pretrained(str(self.embedding_path), padding_side="left")
            self.embedding_model = AutoModel.from_pretrained(str(self.embedding_path), **kwargs).eval()
            if cuda_available():
                self.embedding_model.to("cuda")
            self.active = "embedding"

    def ensure_reranker(self) -> None:
        with self.lock:
            if self.active == "reranker" and self.rerank_model is not None:
                return
            self.unload_all()
            kwargs: dict[str, Any] = {"torch_dtype": preferred_dtype()} if cuda_available() else {}
            self.rerank_tokenizer = AutoTokenizer.from_pretrained(str(self.reranker_path), padding_side="left")
            self.rerank_model = AutoModelForCausalLM.from_pretrained(str(self.reranker_path), **kwargs).eval()
            if cuda_available():
                self.rerank_model.to("cuda")
            self.rerank_false_id = self.rerank_tokenizer.convert_tokens_to_ids("no")
            self.rerank_true_id = self.rerank_tokenizer.convert_tokens_to_ids("yes")
            prefix = (
                "<|im_start|>system\n"
                "Judge whether the Document meets the requirements based on the Query and the Instruct provided. "
                "Note that the answer can only be \"yes\" or \"no\"."
                "<|im_end|>\n<|im_start|>user\n"
            )
            suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
            self.rerank_prefix_tokens = self.rerank_tokenizer.encode(prefix, add_special_tokens=False)
            self.rerank_suffix_tokens = self.rerank_tokenizer.encode(suffix, add_special_tokens=False)
            self.active = "reranker"

    def embedding_device(self) -> str:
        if self.embedding_model is None:
            return "not-loaded"
        return str(next(self.embedding_model.parameters()).device)

    def reranker_device(self) -> str:
        if self.rerank_model is None:
            return "not-loaded"
        return str(next(self.rerank_model.parameters()).device)

    @torch.no_grad()
    def embed(self, texts: list[str], *, instruction: str | None, is_query: bool, dimensions: int | None) -> list[list[float]]:
        self.ensure_embedding()
        assert self.embedding_tokenizer is not None and self.embedding_model is not None
        task = instruction or DEFAULT_TASK
        prepared = [detailed_query(task, text) if is_query else text for text in texts]
        batch = self.embedding_tokenizer(
            prepared,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        batch = {k: v.to(self.embedding_model.device) for k, v in batch.items()}
        outputs = self.embedding_model(**batch)
        embeddings = last_token_pool(outputs.last_hidden_state, batch["attention_mask"])
        embeddings = F.normalize(embeddings, p=2, dim=1)
        if dimensions is not None and dimensions < embeddings.shape[1]:
            embeddings = embeddings[:, :dimensions]
            embeddings = F.normalize(embeddings, p=2, dim=1)
        return embeddings.detach().cpu().float().tolist()

    def format_rerank_pair(self, instruction: str, query: str, doc: str) -> str:
        return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"

    def process_rerank_inputs(self, pairs: list[str], max_length: int) -> dict[str, torch.Tensor]:
        assert self.rerank_tokenizer is not None
        assert self.rerank_prefix_tokens is not None and self.rerank_suffix_tokens is not None
        budget = max_length - len(self.rerank_prefix_tokens) - len(self.rerank_suffix_tokens)
        if budget < 32:
            raise ValueError("max_length too small for reranker prompt")
        inputs = self.rerank_tokenizer(
            pairs,
            padding=False,
            truncation="longest_first",
            return_attention_mask=False,
            max_length=budget,
        )
        for i, item in enumerate(inputs["input_ids"]):
            inputs["input_ids"][i] = self.rerank_prefix_tokens + item + self.rerank_suffix_tokens
        padded = self.rerank_tokenizer.pad(inputs, padding=True, return_tensors="pt", max_length=max_length)
        assert self.rerank_model is not None
        return {k: v.to(self.rerank_model.device) for k, v in padded.items()}

    @torch.no_grad()
    def rerank(self, query: str, documents: list[str], *, instruction: str | None, max_length: int | None) -> list[float]:
        self.ensure_reranker()
        assert self.rerank_model is not None
        assert self.rerank_true_id is not None and self.rerank_false_id is not None
        task = instruction or DEFAULT_TASK
        limit = max_length or self.max_length
        pairs = [self.format_rerank_pair(task, query, doc) for doc in documents]
        inputs = self.process_rerank_inputs(pairs, limit)
        logits = self.rerank_model(**inputs).logits[:, -1, :]
        true_vector = logits[:, self.rerank_true_id]
        false_vector = logits[:, self.rerank_false_id]
        scores = torch.stack([false_vector, true_vector], dim=1)
        scores = torch.nn.functional.log_softmax(scores, dim=1)
        return scores[:, 1].exp().detach().cpu().float().tolist()


def build_app(manager: ModelManager) -> FastAPI:
    app = FastAPI(title="Qwen3 4B Shared Local Service", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        gpu_mem = None
        if cuda_available():
            free, total = torch.cuda.mem_get_info()
            gpu_mem = {"free_mb": round(free / 1024 / 1024, 1), "total_mb": round(total / 1024 / 1024, 1)}
        return {
            "status": "ok",
            "active_model": manager.active,
            "device": "cuda" if cuda_available() else "cpu",
            "device_name": device_name(),
            "gpu_memory": gpu_mem,
            "embedding_model": "qwen3-embedding-4b-local",
            "rerank_model": "qwen3-reranker-4b-local",
            "embedding_path": str(manager.embedding_path),
            "reranker_path": str(manager.reranker_path),
            "max_length": manager.max_length,
        }

    @app.get("/models")
    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": "qwen3-embedding-4b-local", "object": "model", "type": "embedding"},
                {"id": "qwen3-reranker-4b-local", "object": "model", "type": "rerank"},
            ],
        }

    @app.post("/v1/embeddings")
    @app.post("/embeddings")
    def embeddings(req: EmbeddingRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        manager.check_auth(authorization)
        texts = [req.input] if isinstance(req.input, str) else list(req.input)
        if not texts or not all(isinstance(x, str) for x in texts):
            raise HTTPException(status_code=400, detail="input must be a string or list of strings")
        vectors = manager.embed(texts, instruction=req.instruction, is_query=req.is_query, dimensions=req.dimensions)
        usage_tokens = sum(max(1, len(t) // 4) for t in texts)
        return {
            "object": "list",
            "model": req.model or "qwen3-embedding-4b-local",
            "data": [
                {"object": "embedding", "index": i, "embedding": vector}
                for i, vector in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": usage_tokens, "total_tokens": usage_tokens},
        }

    @app.post("/rerank")
    @app.post("/v1/rerank")
    def rerank(req: RerankRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        manager.check_auth(authorization)
        if not req.query.strip():
            raise HTTPException(status_code=400, detail="query must be non-empty")
        if not req.documents:
            return {"id": f"qwen3-rerank-{now_ms()}", "model": req.model or "qwen3-reranker-4b-local", "results": [], "usage": {"total_tokens": 0}}
        scores = manager.rerank(req.query, req.documents, instruction=req.instruction, max_length=req.max_length)
        rows = []
        for i, score in enumerate(scores):
            row: dict[str, Any] = {"index": i, "relevance_score": float(score), "score": float(score)}
            if req.return_documents:
                row["document"] = {"text": req.documents[i]}
            rows.append(row)
        rows.sort(key=lambda x: x["relevance_score"], reverse=True)
        if req.top_n:
            rows = rows[: req.top_n]
        token_est = max(1, (len(req.query) + sum(len(d) for d in req.documents)) // 4)
        return {
            "id": f"qwen3-rerank-{now_ms()}",
            "model": req.model or "qwen3-reranker-4b-local",
            "results": rows,
            "usage": {"total_tokens": token_est},
        }

    @app.post("/unload")
    def unload(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        manager.check_auth(authorization)
        manager.unload_all()
        return {"status": "ok", "active_model": manager.active}

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen3 4B shared embedding/reranker service")
    parser.add_argument("--host", default=os.environ.get("QWEN3_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QWEN3_PORT", "8010")))
    parser.add_argument("--embedding-path", default=os.environ.get("QWEN3_EMBEDDING_PATH", str(DEFAULT_EMBEDDING_PATH)))
    parser.add_argument("--reranker-path", default=os.environ.get("QWEN3_RERANKER_PATH", str(DEFAULT_RERANKER_PATH)))
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--max-length", type=int, default=int(os.environ.get("QWEN3_MAX_LENGTH", "4096")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_path = Path(args.embedding_path)
    reranker_path = Path(args.reranker_path)
    if not embedding_path.exists():
        raise SystemExit(f"Embedding path does not exist: {embedding_path}")
    if not reranker_path.exists():
        raise SystemExit(f"Reranker path does not exist: {reranker_path}")
    manager = ModelManager(embedding_path, reranker_path, args.max_length, args.api_key)
    app = build_app(manager)
    print("Qwen3 shared service starting", flush=True)
    print(f"host={args.host} port={args.port}", flush=True)
    print(f"embedding={embedding_path}", flush=True)
    print(f"reranker={reranker_path}", flush=True)
    print(f"device={'cuda' if cuda_available() else 'cpu'} {device_name()}", flush=True)
    print("mode=lazy-single-model", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
