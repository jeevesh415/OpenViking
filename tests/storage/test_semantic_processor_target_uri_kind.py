# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from openviking.storage.queuefs.semantic_dag import DagStats
from openviking.storage.queuefs.semantic_processor import SemanticProcessor


class _FakeVikingFS:
    def __init__(self):
        self.removed = []
        self.moved = []
        self.created = []
        self.listed = []

    async def exists(self, uri, ctx=None):
        return uri == "viking://resources/upload_123"

    async def stat(self, uri, ctx=None):
        if uri == "viking://resources/upload_123":
            return {"isDir": False}
        raise FileNotFoundError(uri)

    async def rm(self, uri, recursive=False, ctx=None):
        self.removed.append((uri, recursive))

    async def mkdir(self, uri, exist_ok=False, ctx=None):
        self.created.append((uri, exist_ok))

    async def mv(self, old_uri, new_uri, ctx=None):
        self.moved.append((old_uri, new_uri))

    async def ls(self, uri, show_all_hidden=False, ctx=None):
        self.listed.append(uri)
        return []


class _CapturingExecutor:
    last_init = None

    def __init__(self, **kwargs):
        type(self).last_init = kwargs

    async def run(self, root_uri):
        self.root_uri = root_uri

    def get_stats(self):
        return DagStats()


@pytest.mark.asyncio
async def test_on_dequeue_treats_non_directory_target_as_full_move(monkeypatch) -> None:
    fake_fs = _FakeVikingFS()
    monkeypatch.setattr(
        "openviking.storage.queuefs.semantic_processor.get_viking_fs",
        lambda: fake_fs,
    )
    monkeypatch.setattr(
        "openviking.storage.queuefs.semantic_processor.resolve_telemetry",
        lambda _telemetry_id: None,
    )
    monkeypatch.setattr(
        "openviking.storage.queuefs.semantic_processor.SemanticDagExecutor",
        _CapturingExecutor,
    )

    processor = SemanticProcessor()
    data = {
        "uri": "viking://temp/03171434_abcd/upload_123",
        "target_uri": "viking://resources/upload_123",
        "context_type": "resource",
        "account_id": "default",
        "user_id": "default",
        "agent_id": "default",
        "role": "root",
    }

    await processor.on_dequeue(data)

    assert _CapturingExecutor.last_init is not None
    assert _CapturingExecutor.last_init["incremental_update"] is False


@pytest.mark.asyncio
async def test_sync_topdown_replaces_non_directory_target(monkeypatch) -> None:
    fake_fs = _FakeVikingFS()
    monkeypatch.setattr(
        "openviking.storage.queuefs.semantic_processor.get_viking_fs",
        lambda: fake_fs,
    )

    processor = SemanticProcessor()
    diff = await processor._sync_topdown_recursive(
        "viking://temp/03171434_abcd/upload_123",
        "viking://resources/upload_123",
    )

    assert fake_fs.listed == []
    assert fake_fs.removed == [("viking://resources/upload_123", True)]
    assert fake_fs.created == [("viking://resources", True)]
    assert fake_fs.moved == [
        ("viking://temp/03171434_abcd/upload_123", "viking://resources/upload_123")
    ]
    assert diff.added_dirs == ["viking://temp/03171434_abcd/upload_123"]
