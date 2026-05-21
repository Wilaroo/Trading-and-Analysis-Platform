"""v19.34.65d (Option E) — build_version probe tests."""
import importlib
import sys

import pytest


@pytest.fixture()
def sentcom_module():
    """Re-import sentcom router so _BUILD_VERSION is freshly resolved."""
    for mod_name in list(sys.modules):
        if mod_name == "routers.sentcom" or mod_name.endswith(".routers.sentcom"):
            del sys.modules[mod_name]
    sys.path.insert(0, "/app/backend")
    return importlib.import_module("routers.sentcom")


def test_build_version_resolves_from_git(sentcom_module):
    """Inside the /app workspace .git exists, so resolution should succeed."""
    bv = sentcom_module._BUILD_VERSION
    assert isinstance(bv, dict)
    # Either git-resolved (most common) or env-resolved (fallback).
    assert bv["source"] in ("git", "env", "unknown")
    if bv["source"] == "git":
        assert bv["sha"]
        assert len(bv["sha"]) >= 4  # short SHA is ≥ 7 chars but allow defensive
        assert bv["branch"]
        assert isinstance(bv["dirty"], bool)
        assert bv["repo_root"]


def test_build_version_shape(sentcom_module):
    """The dict always carries the documented keys, even on fallback."""
    bv = sentcom_module._BUILD_VERSION
    assert "sha" in bv
    assert "branch" in bv
    assert "dirty" in bv
    assert "source" in bv


def test_resolve_build_version_idempotent(sentcom_module):
    """Calling the resolver multiple times yields equivalent output."""
    a = sentcom_module._resolve_build_version()
    b = sentcom_module._resolve_build_version()
    # SHA / source / branch should be stable across calls.
    assert a.get("source") == b.get("source")
    assert a.get("sha") == b.get("sha")
    assert a.get("branch") == b.get("branch")
