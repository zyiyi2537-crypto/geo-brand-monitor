"""候选 query 聚类 — 本地 sentence-transformers + K-Means。

picker 端把 200 条 LLM/autocomplete 候选按 intent(费用/资质/对比/...)折叠分组,
让用户挑 50 条时看到 intent 覆盖度,不至于一不小心选偏。

设计:
- 模型 paraphrase-multilingual-MiniLM-L12-v2(384 dim,多语言,CPU 跑得动)
- 全局单例,lazy load,首次调用 ~5-10s 加载;之后内存常驻 ~600MB
- 阻塞推理走 asyncio.to_thread,不堵 event loop
- K-Means + silhouette auto-K 都是纯 stdlib(从 geo_prompt.py 提炼)
- 簇标签用 medoid(离中心最近的 prompt 原文),不再调 LLM 二次打标

性能:200 条 CPU 嵌入 ~2-3s;K-Means + sweep ~50ms;整体增量 ~3s,
远小于 DeepSeek 30-90s,picker 体感无差。
"""
from __future__ import annotations

import asyncio
import math
import random
from typing import Optional

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_MODEL = None  # 全局单例


def _load_model():
    """首次调用时加载模型,后续直接返回。线程安全(GIL + 简单赋值)。"""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # 延迟 import
        _MODEL = SentenceTransformer(_MODEL_NAME)
    return _MODEL


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """同步嵌入。模型 normalize_embeddings=True 直接出 L2-normalized 向量。"""
    model = _load_model()
    vecs = model.encode(
        texts, batch_size=32, show_progress_bar=False,
        normalize_embeddings=True, convert_to_numpy=True,
    )
    return [list(map(float, v)) for v in vecs]


async def embed(texts: list[str]) -> list[list[float]]:
    """异步嵌入。走 to_thread 不堵 event loop。"""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)


# ─── 纯 stdlib 向量数学 ────────────────────────────


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _normalize(vec: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in vec))
    if s == 0:
        return vec
    return [x / s for x in vec]


# ─── K-Means(cosine,k-means++ init)─────────────


def _kmeans_pp_init(vectors: list[list[float]], k: int, seed: int = 42) -> list[list[float]]:
    rng = random.Random(seed)
    n = len(vectors)
    if n == 0 or k <= 0:
        return []
    if k >= n:
        return [list(v) for v in vectors]
    centers = [list(vectors[rng.randint(0, n - 1)])]
    while len(centers) < k:
        dists = []
        for v in vectors:
            max_sim = max(_dot(v, c) for c in centers)
            dists.append(max(0.0, 2.0 * (1.0 - max_sim)))
        total = sum(dists)
        if total <= 0:
            centers.append(list(vectors[rng.randint(0, n - 1)]))
            continue
        r = rng.random() * total
        cum, idx = 0.0, 0
        for i, d in enumerate(dists):
            cum += d
            if cum >= r:
                idx = i
                break
        centers.append(list(vectors[idx]))
    return centers


def _kmeans_cosine(vectors: list[list[float]], k: int,
                   max_iters: int = 25, seed: int = 42):
    """Returns (labels, centers, inertia). 输入须 L2-normalized。"""
    n = len(vectors)
    if n == 0:
        return [], [], 0.0
    if k <= 0:
        return [0] * n, [], 0.0
    if k >= n:
        return list(range(n)), [list(v) for v in vectors], 0.0

    centers = _kmeans_pp_init(vectors, k, seed=seed)
    labels = [-1] * n
    dim = len(vectors[0])

    for _ in range(max_iters):
        new_labels = []
        for v in vectors:
            best_i, best_sim = 0, -2.0
            for i, c in enumerate(centers):
                s = _dot(v, c)
                if s > best_sim:
                    best_sim, best_i = s, i
            new_labels.append(best_i)
        if new_labels == labels:
            break
        labels = new_labels

        sums = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for v, l in zip(vectors, labels):
            sv = sums[l]
            for d in range(dim):
                sv[d] += v[d]
            counts[l] += 1
        new_centers = []
        for i in range(k):
            if counts[i] == 0:
                new_centers.append(list(vectors[(i * 31 + 7) % n]))
            else:
                mean = [s / counts[i] for s in sums[i]]
                new_centers.append(_normalize(mean))
        centers = new_centers

    inertia = sum(max(0.0, 2.0 * (1.0 - _dot(v, centers[l])))
                  for v, l in zip(vectors, labels))
    return labels, centers, inertia


# ─── Auto-K via sampled silhouette ────────────────


def _sample_silhouette(vectors: list[list[float]], labels: list[int],
                       sample_size: int = 120, seed: int = 42) -> float:
    n = len(vectors)
    if n < 4:
        return 0.0
    clusters: dict[int, list[int]] = {}
    for i, l in enumerate(labels):
        clusters.setdefault(l, []).append(i)
    if len(clusters) < 2:
        return 0.0

    rng = random.Random(seed)
    sample = rng.sample(range(n), min(sample_size, n))

    total, counted = 0.0, 0
    for i in sample:
        my = labels[i]
        same = [j for j in clusters[my] if j != i]
        if not same:
            continue
        a = sum(2.0 * (1.0 - _dot(vectors[i], vectors[j])) for j in same) / len(same)
        b = float("inf")
        for l, members in clusters.items():
            if l == my:
                continue
            d = sum(2.0 * (1.0 - _dot(vectors[i], vectors[j])) for j in members) / len(members)
            if d < b:
                b = d
        if b == float("inf"):
            continue
        denom = max(a, b)
        if denom == 0:
            continue
        total += (b - a) / denom
        counted += 1
    return (total / counted) if counted else 0.0


def _pick_k_auto(vectors: list[list[float]], k_min: int = 3, k_max: int = 8) -> int:
    n = len(vectors)
    if n < 6:
        return min(2, n)
    k_max = max(k_min, min(k_max, n - 1))
    best_k, best_sil = k_min, -2.0
    for k in range(k_min, k_max + 1):
        labels, _centers, _inertia = _kmeans_cosine(vectors, k, max_iters=8)
        sil = _sample_silhouette(vectors, labels)
        if sil > best_sil:
            best_sil, best_k = sil, k
    return best_k


# ─── Public entry ─────────────────────────────────


async def cluster_candidates(
    texts: list[str], k: Optional[int] = None,
) -> tuple[list[int], list[dict]]:
    """嵌入 + K-Means + medoid 标签。

    Args:
        texts: 候选文本列表
        k: 簇数,None 走 auto-K(silhouette 在 3-8 之间扫)

    Returns:
        (labels, clusters_meta):
          labels[i] = texts[i] 所属 cluster_id(0-indexed)
          clusters_meta = [{cluster_id, label, size, medoid_index}, ...] 按 size 降序
    """
    n = len(texts)
    if n < 4:
        # 太少不聚类,所有一簇
        return [0] * n, [{
            "cluster_id": 0, "label": texts[0] if texts else "",
            "size": n, "medoid_index": 0,
        }]

    vectors = await embed(texts)
    chosen_k = k if k else _pick_k_auto(vectors)
    labels, centers, _inertia = _kmeans_cosine(vectors, chosen_k)

    # 每簇取 medoid(离中心最近的样本)作 label
    by_cluster: dict[int, list[int]] = {}
    for i, l in enumerate(labels):
        by_cluster.setdefault(l, []).append(i)

    clusters_meta = []
    for cid, indices in by_cluster.items():
        c = centers[cid]
        best_i, best_s = indices[0], -2.0
        for i in indices:
            s = _dot(vectors[i], c)
            if s > best_s:
                best_s, best_i = s, i
        clusters_meta.append({
            "cluster_id": int(cid),
            "label": texts[best_i],
            "size": len(indices),
            "medoid_index": best_i,
        })
    clusters_meta.sort(key=lambda c: c["size"], reverse=True)
    return labels, clusters_meta
