#!/usr/bin/env python3
"""
Батч-кластеризация заявок обратной связи.

Алгоритм:
  1. Загрузить незакреплённые feedback (cluster_id IS NULL)
  2. TF-IDF векторизация комментариев
  3. Косинусное сходство → граф рёбер с weight >= THRESHOLD
  4. Connected components → кластеры
  5. Для каждого кластера: создать feedback_cluster, назначить feedback

Запуск:
  python3 tools/feedback_cluster.py [--threshold 0.45] [--min-size 2]

LLM для заголовков:
  Опциональный флаг --llm: вызывает локальный Ollama/OpenAI-совместимый
  эндпоинт для генерации заголовка по текстам кластера.
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import journal_feedback


def _tfidf_cosine(docs: list[str]) -> list[list[float]]:
    """Минимальная TF-IDF без зависимостей."""
    import math
    import re

    def tokenize(text):
        return re.findall(r'\w+', text.lower(), re.UNICODE)

    all_tokens: list[list[str]] = [tokenize(d) for d in docs]
    df: dict[str, int] = {}
    for tokens in all_tokens:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    n = len(docs)

    def tfidf_vec(tokens):
        tf: dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        total = max(len(tokens), 1)
        vec: dict[str, float] = {}
        for t, cnt in tf.items():
            idf = math.log(n / (df.get(t, 1)))
            vec[t] = (cnt / total) * idf
        return vec

    vecs = [tfidf_vec(t) for t in all_tokens]

    def cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    n = len(vecs)
    return [[cosine(vecs[i], vecs[j]) for j in range(n)] for i in range(n)]


def connected_components(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    """Union-Find для соединённых компонент."""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for a, b in edges:
        union(a, b)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())


def _llm_title(texts: list[str], llm_url: str) -> str | None:
    """Вызвать LLM (OpenAI-совместимый) для генерации заголовка кластера."""
    import json
    import urllib.request

    sample = "\n".join(f"- {t}" for t in texts[:5])
    prompt = (
        "Дай короткий заголовок (до 80 символов) для группы похожих отзывов пользователей. "
        "Только заголовок, без объяснений.\n\n" + sample
    )
    payload = json.dumps({
        "model": "qwen2.5:7b",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 60,
        "temperature": 0.3,
    }).encode()
    try:
        req = urllib.request.Request(
            llm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
        return d["choices"][0]["message"]["content"].strip()[:80]
    except Exception as e:
        print(f"  LLM error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.45,
                        help="Порог косинусного сходства (0–1)")
    parser.add_argument("--min-size",  type=int,   default=2,
                        help="Минимальный размер кластера")
    parser.add_argument("--llm",       type=str,   default=None,
                        help="URL OpenAI-совместимого LLM для заголовков (необязательно)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Не записывать в БД, только показать кластеры")
    args = parser.parse_args()

    feedbacks = journal_feedback.get_unassigned_feedback(limit=500)
    if not feedbacks:
        print("Нет незакреплённых заявок.")
        return

    print(f"Загружено {len(feedbacks)} незакреплённых заявок.")
    docs = [fb["comment"] or "" for fb in feedbacks]
    n = len(docs)

    # Удалить слишком короткие комменты — они плохо векторизуются
    valid = [(i, docs[i]) for i in range(n) if len(docs[i]) >= 10]
    if not valid:
        print("Нет заявок с достаточным текстом для кластеризации.")
        return

    valid_idx = [v[0] for v in valid]
    valid_docs = [v[1] for v in valid]
    nv = len(valid_docs)
    print(f"  Векторизуем {nv} заявок (TF-IDF cosine)…")
    sim = _tfidf_cosine(valid_docs)

    edges = []
    for i in range(nv):
        for j in range(i + 1, nv):
            if sim[i][j] >= args.threshold:
                edges.append((i, j))

    print(f"  Рёбра: {len(edges)} (threshold={args.threshold})")
    components = connected_components(nv, edges)
    clusters = [c for c in components if len(c) >= args.min_size]
    print(f"  Найдено {len(clusters)} кластеров (min_size={args.min_size})")

    for comp in clusters:
        fb_ids   = [feedbacks[valid_idx[i]]["id"] for i in comp]
        comments = [feedbacks[valid_idx[i]]["comment"] for i in comp]
        title = comments[0][:80] if comments else "Без заголовка"

        if args.llm:
            llm_title = _llm_title(comments, args.llm)
            if llm_title:
                title = llm_title

        print(f"  Кластер {len(comp)} шт.: «{title[:60]}…»")
        if not args.dry_run:
            result = journal_feedback.create_cluster_from_feedbacks(fb_ids, title)
            if result["ok"]:
                print(f"    → cluster_id={result['cluster_id']} weight={result['total_weight']}")

    if args.dry_run:
        print("Dry-run: изменения не сохранены.")
    else:
        print("Готово.")


if __name__ == "__main__":
    main()
