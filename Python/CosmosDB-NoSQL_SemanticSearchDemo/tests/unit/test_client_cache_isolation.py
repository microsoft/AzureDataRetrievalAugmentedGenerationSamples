from functools import lru_cache
from types import SimpleNamespace

import pytest

import search_demo


def test_all_application_caches_start_empty():
    for factory in (search_demo.get_credential, search_demo.get_cosmos_client,
                    search_demo.get_inference_client, search_demo.get_embedding_client):
        assert factory.cache_info().currsize == 0


def test_cached_embedding_cannot_cross_environment_boundary(client_cache_scope, monkeypatch):
    closed = []

    class Client:
        def close(self):
            closed.append(self)

    sdk = SimpleNamespace(Client=Client)

    @lru_cache(maxsize=1)
    def embedding_client():
        if not search_demo.os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
            raise search_demo.SearchError("Configure AZURE_OPENAI_EMBEDDING_DEPLOYMENT.")
        return sdk.Client()

    with client_cache_scope((embedding_client,), ((sdk, "Client"),)):
        monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "offline-test-deployment")
        first = embedding_client()
        assert embedding_client() is first
    assert closed == [first]
    monkeypatch.delenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    with client_cache_scope((embedding_client,), ((sdk, "Client"),)):
        with pytest.raises(search_demo.SearchError, match="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
            embedding_client()
    assert closed == [first], "Cleanup must not invoke factories or create another client."


def test_evicted_clients_close_before_credential_even_when_test_fails(client_cache_scope):
    closed = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    sdk = SimpleNamespace(Credential=Resource, Client=Resource)

    @lru_cache(maxsize=1)
    def credential():
        return sdk.Credential("credential")

    @lru_cache(maxsize=1)
    def client(name):
        credential()
        return sdk.Client(name)

    with pytest.raises(ValueError, match="test failed"):
        with client_cache_scope((credential, client), ((sdk, "Credential"), (sdk, "Client"))):
            client("first")
            client("second")  # Evicts first; it must still be closed.
            raise ValueError("test failed")
    assert closed == ["second", "first", "credential"]
    assert credential.cache_info().currsize == client.cache_info().currsize == 0
    assert sdk.Client is Resource and sdk.Credential is Resource


def test_cleanup_failure_still_closes_other_clients_and_clears_cache(client_cache_scope):
    closed = []

    class Client:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)
            if self.name == "broken":
                raise RuntimeError("close failed")

    sdk = SimpleNamespace(Client=Client)

    @lru_cache(maxsize=4)
    def client(name):
        return sdk.Client(name)

    with pytest.raises(RuntimeError, match="close failed"):
        with client_cache_scope((client,), ((sdk, "Client"),)):
            client("healthy")
            client("broken")
    assert closed == ["broken", "healthy"]
    assert client.cache_info().currsize == 0
