import os
import ipaddress
import socket
from contextlib import contextmanager, ExitStack
from importlib import import_module

import pytest

import search_demo


# Keep original wrappers: individual tests may monkeypatch their module names.
_CLIENT_FACTORIES = (
    search_demo.get_credential,
    search_demo.get_cosmos_client,
    search_demo.get_inference_client,
    search_demo.get_embedding_client,
)


@contextmanager
def _client_cache_scope(factories, constructor_targets):
    """Own test-created clients, including evicted entries and imported factory aliases."""
    factories = tuple(factories)
    for factory in factories:
        factory.cache_clear()
    with pytest.MonkeyPatch.context() as patches, ExitStack() as resources:
        owned = set()

        def track(constructor):
            def create(*args, **kwargs):
                instance = constructor(*args, **kwargs)
                close = getattr(instance, "close", None)
                if callable(close) and id(instance) not in owned:
                    owned.add(id(instance))
                    # LIFO closes clients before the credential they depend on.
                    # Retain the bound closer even if the LRU later evicts the client.
                    resources.callback(close)
                return instance
            return create

        for module, name in constructor_targets:
            patches.setattr(module, name, track(getattr(module, name)))
        try:
            yield
        finally:
            try:
                # Never call a cached factory during cleanup: that could create a client.
                resources.close()
            finally:
                for factory in factories:
                    factory.cache_clear()


@pytest.fixture
def client_cache_scope():
    """Expose the test-only lifecycle helper for offline regression tests."""
    return _client_cache_scope


@pytest.fixture(autouse=True)
def isolate_client_caches(offline_guard):
    # The guard sets/validates this test's environment before clients can be created.
    # Track SDK constructors rather than replacing factory functions, so aliases
    # imported with "from search_demo import ..." use the same isolated caches.
    targets = (
        (import_module("azure.identity"), "DefaultAzureCredential"),
        (import_module("azure.cosmos"), "CosmosClient"),
        (import_module("azure.data.ai"), "InferenceClient"),
        (import_module("openai"), "AzureOpenAI"),
    )
    with _client_cache_scope(_CLIENT_FACTORIES, targets):
        yield


@pytest.fixture(autouse=True)
def offline_guard(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        if os.getenv("RUN_LIVE_TESTS") != "1":
            pytest.skip("Set RUN_LIVE_TESTS=1 to enable Azure tests.")
        for key in ("COSMOS_URI", "COSMOS_DB_DATABASE", "AZURE_AI_INFERENCE_ENDPOINT"):
            if not os.getenv(key):
                pytest.fail(f"Live tests enabled but {key} is missing.")
        return

    def is_loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host in ("localhost", b"localhost")

    def guard_connection(original):
        def guarded(connection, address):
            if not isinstance(address, tuple) or not is_loopback(address[0]):
                raise AssertionError("Offline test attempted external network access")
            return original(connection, address)
        return guarded

    # Windows asyncio creates a loopback socketpair for its wake-up pipe.
    # Permit local runtime IPC, not Azure/service connections.
    monkeypatch.setattr(socket.socket, "connect", guard_connection(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connection(socket.socket.connect_ex))
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo

    def guarded_sendto(connection, *args):
        address = args[-1]
        if not isinstance(address, tuple) or not is_loopback(address[0]):
            raise AssertionError("Offline test attempted external network access")
        return original_sendto(connection, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_loopback(host):
            raise AssertionError("Offline test attempted external DNS/network access")
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    # No local developer configuration may leak into offline tests.
    monkeypatch.setenv("DEMO_LOAD_DOTENV", "false")
    for key in ("COSMOS_URI", "COSMOS_DB_DATABASE", "AZURE_AI_INFERENCE_ENDPOINT",
                "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
        monkeypatch.delenv(key, raising=False)
