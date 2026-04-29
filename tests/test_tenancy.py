"""Multi-tenancy isolation tests for ClawFS core."""
from __future__ import annotations

import pytest

from clawfs.core import ClawFS


@pytest.fixture
def fs(tmp_path):
    return ClawFS.local(str(tmp_path))


def test_two_tenants_cannot_see_each_others_refs(fs):
    fs.put_ref("alpha.txt", b"from-A", tenant_id="tenant-a")
    fs.put_ref("alpha.txt", b"from-B", tenant_id="tenant-b")

    a_paths = [r.path for r in fs.list_refs(tenant_id="tenant-a")]
    b_paths = [r.path for r in fs.list_refs(tenant_id="tenant-b")]

    assert "alpha.txt" in a_paths
    assert "alpha.txt" in b_paths
    # but their resolved content stays separate
    assert fs.resolve_ref("alpha.txt", tenant_id="tenant-a") == b"from-A"
    assert fs.resolve_ref("alpha.txt", tenant_id="tenant-b") == b"from-B"


def test_dedup_still_works_across_tenants(fs):
    """Same content from two tenants should land in one storage blob."""
    same = b"shared content"
    h1, _ = fs.put_ref("x.txt", same, tenant_id="t1")
    h2, _ = fs.put_ref("y.txt", same, tenant_id="t2")
    assert h1 == h2
    # Both can fetch by hash (blobs are content-addressed; privacy is via refs)
    assert fs.get_blob(h1, tenant_id="t1") == same
    assert fs.get_blob(h1, tenant_id="t2") == same


def test_delete_ref_in_one_tenant_does_not_break_other(fs):
    same = b"shared content"
    fs.put_ref("a.txt", same, tenant_id="t1")
    fs.put_ref("b.txt", same, tenant_id="t2")
    assert fs.delete_ref("a.txt", tenant_id="t1") is True
    # Other tenant's ref + blob still intact
    assert fs.resolve_ref("b.txt", tenant_id="t2") == same


def test_delete_ref_in_tenant_does_not_affect_other_tenants_listing(fs):
    fs.put_ref("only-mine.txt", b"x", tenant_id="t1")
    assert [r.path for r in fs.list_refs(tenant_id="t2")] == []


def test_list_prefix_is_tenant_scoped(fs):
    fs.put_ref("a/1", b"_", tenant_id="t1")
    fs.put_ref("a/2", b"_", tenant_id="t2")
    assert {r.path for r in fs.list_refs("a/", tenant_id="t1")} == {"a/1"}
    assert {r.path for r in fs.list_refs("a/", tenant_id="t2")} == {"a/2"}


def test_share_resolves_only_to_that_tenants_ref(fs):
    fs.put_ref("doc", b"A-doc", tenant_id="t1")
    fs.put_ref("doc", b"B-doc", tenant_id="t2")
    a_token = fs.create_share("doc", tenant_id="t1")
    b_token = fs.create_share("doc", tenant_id="t2")
    assert fs.resolve_share(a_token) == b"A-doc"
    assert fs.resolve_share(b_token) == b"B-doc"


def test_tenant_for_token_lookup(fs):
    fs.upsert_tenant("acme", name="Acme Corp", tokens=["sk_acme_123"])
    fs.upsert_tenant("globex", name="Globex", tokens=["sk_globex_456"])
    assert fs.tenant_for_token("sk_acme_123") == "acme"
    assert fs.tenant_for_token("sk_globex_456") == "globex"
    assert fs.tenant_for_token("bogus") is None
