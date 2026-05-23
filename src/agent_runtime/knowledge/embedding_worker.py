from __future__ import annotations

import json
import sys

from agent_runtime.knowledge.embedding import LocalEmbeddingProvider


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    model_path = payload["model_path"]
    mode = payload["mode"]
    inputs = payload["inputs"]

    provider = LocalEmbeddingProvider(model_path)
    if mode == "query":
        vectors = [provider.embed_query(inputs[0])]
    elif mode == "documents":
        vectors = provider.embed_documents(inputs)
    else:
        raise ValueError(f"unsupported embedding worker mode: {mode}")

    sys.stdout.write(json.dumps({"vectors": vectors}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
