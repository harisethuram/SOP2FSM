"""Embedding service: embed check_text, normalize, compare with existing (cosine similarity)."""
from pathlib import Path
import numpy as np

# Lazy-load model to avoid slow startup
_model = None
_embedding_dim = None
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# embs
def _get_model():
    global _model, _embedding_dim
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _embedding_dim = _model.get_sentence_embedding_dimension()
    return _model, _embedding_dim


def embed_text(text: str) -> np.ndarray:
    """Return normalized unit vector for check_text. Shape (embedding_dim,)."""
    model, _ = _get_model()
    emb = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return emb.astype(np.float32)


def get_embedding_dim() -> int:
    _, dim = _get_model()
    return dim


def load_embeddings_tensor():
    """Load embeddings.pt; return shape (n, dim) or (0, dim) if empty."""
    import torch
    p = DATA_DIR / "embeddings.pt"
    if not p.exists():
        _, dim = _get_model()
        return torch.zeros(0, dim, dtype=torch.float32)
    t = torch.load(p, weights_only=True)
    return t


def save_embeddings_tensor(tensor):
    """Save tensor to data/embeddings.pt."""
    import torch
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(tensor, DATA_DIR / "embeddings.pt")


def find_similar_check_ids(check_text: str, threshold: float = 0.7):
    """
    Compare embedded check_text to existing embeddings.
    Return list of (check_index, similarity) for similarities >= threshold.
    check_index aligns with check_ids.yaml row order.
    """
    new_emb = embed_text(check_text)
    tensor = load_embeddings_tensor()
    if tensor.shape[0] == 0:
        return []
    # tensor is (n, dim), new_emb is (dim,); dot product per row
    sims = tensor.numpy() @ new_emb
    result = []
    for i, s in enumerate(sims):
        if float(s) >= threshold:
            result.append((i, float(s)))
    return result


def get_cosine_similarities_to_all(check_text: str):
    """
    Return cosine similarity (dot product on normalized vectors) of check_text
    to every existing canonical check. Row order matches check_ids.yaml.
    Returns list of (check_index, similarity), empty if no existing checks.
    """
    new_emb = embed_text(check_text)
    tensor = load_embeddings_tensor()
    if tensor.shape[0] == 0:
        return []
    sims = tensor.numpy() @ new_emb
    return [(i, float(s)) for i, s in enumerate(sims)]
