import time
import os
import chromadb

# Ensure the memory directory exists
memory_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(memory_dir, "chroma_db")

client = chromadb.PersistentClient(path=db_path)
collection = client.get_or_create_collection("jarvis_memory")

# We will use google-genai for embeddings instead of sentence-transformers
from google import genai

def get_embedding(text: str) -> list[float]:
    """Generates an embedding using Google GenAI."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return []
    try:
        gemini_client = genai.Client(api_key=api_key)
        response = gemini_client.models.embed_content(
            model='text-embedding-004',
            contents=text,
        )
        return response.embeddings[0].values
    except Exception as e:
        print(f"[Memory] Embedding error: {e}")
        return []

def remember(text: str, metadata: dict={}):
    """Embeds the text and saves it to ChromaDB."""
    embedding = get_embedding(text)
    if not embedding:
        return
    collection.add(
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata],
        ids=[str(time.time())]
    )

def recall(query: str, n: int=5) -> list:
    """Searches for the most semantically similar memories to the query."""
    try:
        embedding = get_embedding(query)
        if not embedding:
            return []
        results = collection.query(
            query_embeddings=[embedding],
            n_results=n
        )
        if results['documents'] and len(results['documents']) > 0:
            return results['documents'][0]
        return []
    except Exception as e:
        print(f"[Memory] Recall error: {e}")
        return []
