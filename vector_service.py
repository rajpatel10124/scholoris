import os
import json
import faiss
import numpy as np
from typing import List, Tuple, Dict, Any

# Path to store the FAISS index and metadata
INSTANCE_DIR = os.path.join(os.getcwd(), "instance")
INDEX_PATH = os.path.join(INSTANCE_DIR, "faiss_index.bin")
MAP_PATH = os.path.join(INSTANCE_DIR, "id_map.json")

class VectorService:
    """
    Manages a persistent FAISS index for high-speed semantic similarity search.
    Maps system-wide Submission IDs to their vector embeddings.
    """
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.index = None
        self.id_map = {}  # FAISS_ID (str) -> {submission_id, text_hash}
        self._initialize()

    def _initialize(self):
        """Load existing index or create a new one."""
        if not os.path.exists(INSTANCE_DIR):
            os.makedirs(INSTANCE_DIR, exist_ok=True)
            
        if os.path.exists(INDEX_PATH) and os.path.exists(MAP_PATH):
            try:
                self.index = faiss.read_index(INDEX_PATH)
                with open(MAP_PATH, 'r') as f:
                    self.id_map = json.load(f)
                print(f"[VectorService] Loaded index with {self.index.ntotal} vectors.")
            except Exception as e:
                print(f"[VectorService] Loading error: {e}. Recreating index...")
                self._create_new_index()
        else:
            self._create_new_index()

    def _create_new_index(self):
        """Initialize a new IndexFlatIP (Inner Product) for cosine similarity."""
        # Using IndexFlatIP on normalized vectors is equivalent to cosine similarity
        inner_index = faiss.IndexFlatIP(self.dimension)
        # Wrap with IndexIDMap if we want to use our own 64-bit integer IDs
        self.index = faiss.IndexIDMap(inner_index)
        self.id_map = {}
        print("[VectorService] Created fresh FAISS index.")

    def save(self):
        """Persist index and ID map to disk."""
        try:
            faiss.write_index(self.index, INDEX_PATH)
            with open(MAP_PATH, 'w') as f:
                json.dump(self.id_map, f)
            print("[VectorService] Saved index and map.")
        except Exception as e:
            print(f"[VectorService] Save error: {e}")

    def add_submission(self, submission_id: int, embedding: np.ndarray, text_hash: str):
        """
        Adds a document embedding to the FAISS index.
        Args:
           submission_id: The database ID of the submission.
           embedding: Numpy array of shape (768,).
           text_hash: SHA256 of the extracted text.
        """
        if embedding.shape[0] != self.dimension:
            raise ValueError(f"Dim mismatch: {embedding.shape[0]} vs {self.dimension}")

        # Normalize for cosine similarity
        vec = embedding.astype('float32').reshape(1, -1)
        faiss.normalize_L2(vec)

        # Add to FAISS index with specific ID
        self.index.add_with_ids(vec, np.array([submission_id], dtype='int64'))
        
        # Store metadata mapping
        self.id_map[str(submission_id)] = {
            "submission_id": submission_id,
            "text_hash": text_hash
        }
        self.save()

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves the top-K most similar submission IDs.
        Returns: List of dicts with {submission_id, score, text_hash}
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        # Normalize query vector
        query_vec = query_embedding.astype('float32').reshape(1, -1)
        faiss.normalize_L2(query_vec)

        # FAISS search
        distances, ids = self.index.search(query_vec, top_k)

        results = []
        for dist, idx in zip(distances[0], ids[0]):
            if idx == -1: continue # FAISS returns -1 if not enough results
            
            meta = self.id_map.get(str(idx))
            results.append({
                "submission_id": int(idx),
                "score": float(dist),
                "text_hash": meta.get("text_hash") if meta else None
            })
            
        return results

    def remove_submission(self, submission_id: int):
        """Remove a submission from the index."""
        try:
            self.index.remove_ids(np.array([submission_id], dtype='int64'))
            if str(submission_id) in self.id_map:
                del self.id_map[str(submission_id)]
            self.save()
        except Exception as e:
            print(f"[VectorService] Removal error: {e}")

# Global singleton instance
_vector_service = None

def get_vector_service():
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorService()
    return _vector_service
