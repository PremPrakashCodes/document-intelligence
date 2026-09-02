"""Storage: the interface contract, and R2's error translation."""

import pytest

from storage.base import ObjectNotFound, StorageError, document_key
from storage.memory import InMemoryDocumentStore
from storage.r2 import R2DocumentStore, _is_missing, build_store


class TestDocumentKey:
    def test_groups_everything_for_a_document_under_one_prefix(self):
        assert document_key("doc_1") == "documents/doc_1/source.pdf"
        assert document_key("doc_1", "thumb.png").startswith("documents/doc_1/")


class TestInMemoryStore:
    async def test_round_trips(self, store):
        await store.put("k", b"bytes")
        assert await store.get("k") == b"bytes"
        assert await store.exists("k")

    async def test_missing_key_raises(self, store):
        with pytest.raises(ObjectNotFound):
            await store.get("nope")

    async def test_delete_is_idempotent(self, store):
        await store.put("k", b"x")
        await store.delete("k")
        await store.delete("k")
        assert not await store.exists("k")

    def test_satisfies_the_protocol(self):
        from storage.base import DocumentStore

        assert isinstance(InMemoryDocumentStore(), DocumentStore)


class TestR2:
    def test_recognises_the_shapes_of_a_missing_object(self):
        class Err(Exception):
            def __init__(self, payload):
                self.response = payload

        assert _is_missing(Err({"Error": {"Code": "NoSuchKey"}}))
        assert _is_missing(Err({"Error": {"Code": "404"}}))
        assert _is_missing(Err({"ResponseMetadata": {"HTTPStatusCode": 404}}))
        assert not _is_missing(Err({"Error": {"Code": "AccessDenied"}}))
        assert not _is_missing(Exception("network down"))

    async def test_translates_a_missing_object(self, monkeypatch):
        store = R2DocumentStore(
            endpoint_url="https://example.invalid", access_key_id="a",
            secret_access_key="b", bucket="c",
        )

        class Boom(Exception):
            response = {"Error": {"Code": "NoSuchKey"}}

        class FakeClient:
            def get_object(self, **kwargs):
                raise Boom()

        monkeypatch.setattr(type(store), "_client", property(lambda self: FakeClient()))
        with pytest.raises(ObjectNotFound):
            await store.get("k")

    async def test_translates_other_failures(self, monkeypatch):
        store = R2DocumentStore(
            endpoint_url="https://example.invalid", access_key_id="a",
            secret_access_key="b", bucket="c",
        )

        class FakeClient:
            def get_object(self, **kwargs):
                raise Exception("connection reset")

        monkeypatch.setattr(type(store), "_client", property(lambda self: FakeClient()))
        with pytest.raises(StorageError) as err:
            await store.get("k")
        assert err.value.code == "storage_get_failed"


class TestBuildStore:
    def test_falls_back_when_r2_is_not_configured(self, settings):
        assert isinstance(build_store(settings), InMemoryDocumentStore)

    def test_uses_r2_when_configured(self, settings):
        configured = settings.model_copy(
            update={"r2_access_key_id": "a", "r2_secret_access_key": "b", "r2_bucket_name": "c"}
        )
        assert isinstance(build_store(configured), R2DocumentStore)
