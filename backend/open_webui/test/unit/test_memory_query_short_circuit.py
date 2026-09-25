"""A memory query for someone with no saved memories answers empty without
embedding the question (which would load the embedding model first)."""

import asyncio
import uuid
from types import SimpleNamespace

from open_webui.models.memories import Memories
from open_webui.routers import memories as memories_router


def _request(embed):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(EMBEDDING_FUNCTION=embed)))


def test_no_memories_answers_empty_without_embedding(monkeypatch):
    def embed(*args, **kwargs):
        raise AssertionError("the question must not be embedded")

    user = SimpleNamespace(id=f"memory-none-{uuid.uuid4().hex[:8]}")
    result = asyncio.run(
        memories_router.query_memory(
            _request(embed), memories_router.QueryMemoryForm(content="你好"), user=user
        )
    )
    assert result == {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def test_saved_memories_are_searched(monkeypatch):
    user = SimpleNamespace(id=f"memory-some-{uuid.uuid4().hex[:8]}")
    Memories.insert_new_memory(user.id, "喜欢简洁的回答")
    assert Memories.user_has_memories(user.id) is True

    searched = []

    class FakeVectorDB:
        def search(self, collection_name, vectors, limit):
            searched.append((collection_name, vectors, limit))
            return None

    monkeypatch.setattr(memories_router, "VECTOR_DB_CLIENT", FakeVectorDB())
    asyncio.run(
        memories_router.query_memory(
            _request(lambda text, user=None: [0.1, 0.2]),
            memories_router.QueryMemoryForm(content="你好"),
            user=user,
        )
    )
    assert searched == [(f"user-memory-{user.id}", [[0.1, 0.2]], 1)]
