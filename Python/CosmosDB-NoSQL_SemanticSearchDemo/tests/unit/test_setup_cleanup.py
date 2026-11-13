from unittest.mock import Mock

import pytest

import cleanup
import container_setup as setup


def test_setup_validates_both_before_any_create(monkeypatch):
    bad = setup.container_resource("search_diskann")
    bad["partitionKey"]["paths"] = ["/other"]
    az = Mock(return_value=[{"resource": bad}])
    monkeypatch.setattr(setup, "az_json", az)
    with pytest.raises(ValueError, match="incompatible"):
        setup.setup_containers("sub", "rg", "account", "db", confirm=True)
    assert az.call_count == 1


def test_existing_containers_reused_without_create_or_throughput_change(monkeypatch):
    az = Mock(return_value=[{"resource": setup.container_resource(name)}
                           for name in setup.CONTAINERS])
    monkeypatch.setattr(setup, "az_json", az)
    setup.setup_containers("sub", "rg", "account", "db", confirm=True)
    assert az.call_count == 1
    assert az.call_args.args[:4] == ("cosmosdb", "sql", "container", "list")


def test_missing_requires_explicit_confirmation(monkeypatch):
    az = Mock(return_value=[])
    monkeypatch.setattr(setup, "az_json", az)
    with pytest.raises(ValueError, match="confirm-create"):
        setup.setup_containers("sub", "rg", "account", "db")
    assert az.call_count == 1


def test_authorization_error_is_not_absence(monkeypatch):
    az = Mock(side_effect=RuntimeError("forbidden"))
    monkeypatch.setattr(setup, "az_json", az)
    with pytest.raises(RuntimeError):
        setup.setup_containers("sub", "rg", "account", "db", confirm=True)
    assert az.call_count == 1


def test_cleanup_is_dry_run_by_default(monkeypatch):
    az = Mock(side_effect=AssertionError("No Azure calls allowed"))
    monkeypatch.setattr(cleanup, "az_json", az)
    assert cleanup.main(["--subscription", "sub", "--resource-group", "rg",
                         "--account", "account", "--database", "db",
                         "--container", "search_qflat"]) == 0
    az.assert_not_called()


def test_cleanup_wrong_confirmation_cannot_delete(monkeypatch):
    az = Mock(side_effect=AssertionError("No Azure calls allowed"))
    monkeypatch.setattr(cleanup, "az_json", az)
    assert cleanup.main(["--subscription", "sub", "--resource-group", "rg",
                         "--account", "account", "--database", "db",
                         "--container", "search_qflat", "--confirm-delete", "wrong"]) == 1
    az.assert_not_called()
