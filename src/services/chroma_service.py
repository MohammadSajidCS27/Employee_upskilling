import chromadb
from chromadb.config import Settings

class ChromaDBService:
    def __init__(self, path: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection("learning_resources")

    def add_resources(self, resources: list, embeddings: list = None):
        if embeddings:
            self.collection.add(
                ids=[r["id"] for r in resources],
                embeddings=embeddings,
                metadatas=[{"title": r["title"], "type": r["type"]} for r in resources],
                documents=[r["content"] for r in resources]
            )

    def search(self, query: str, n_results: int = 5):
        return self.collection.query(query_texts=[query], n_results=n_results)

    def get_resource_count(self) -> int:
        return self.collection.count()