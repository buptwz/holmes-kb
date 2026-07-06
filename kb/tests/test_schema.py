"""Tests for kb/holmes/kb/schema.py — schema validation."""

from __future__ import annotations

import pytest

from holmes.kb.schema import validate_entry


def _make_pitfall(extra_fields: str = "", extra_sections: str = "") -> str:
    return f"""\
---
id: PT-DB-001
type: pitfall
title: Redis Connection Timeout
maturity: draft
category: database
tags: [redis, timeout]
created_at: "2026-01-01"
updated_at: "2026-01-01"
{extra_fields}
---

## Symptoms
Connections time out under load.

## Root Cause
Connection pool is too small.

## Resolution
Increase `maxclients` in redis.conf.
{extra_sections}
"""


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def test_valid_pitfall():
    result = validate_entry(_make_pitfall())
    assert result.valid is True
    assert result.errors == []


def test_valid_model():
    content = """\
---
id: MD-SVC-001
type: model
title: Service Mesh
maturity: verified
category: ""
tags: [service-mesh, istio]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Overview
A service mesh is an infrastructure layer for microservice communication.
"""
    result = validate_entry(content)
    assert result.valid is True


def test_valid_guideline():
    content = """\
---
id: GL-GEN-001
type: guideline
title: Never Commit Secrets
maturity: proven
category: ""
tags: [security]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Guideline
Never commit API keys, passwords, or tokens to version control.
"""
    result = validate_entry(content)
    assert result.valid is True


def test_valid_process():
    content = """\
---
id: PR-OPS-001
type: process
title: Deploy Runbook
maturity: draft
category: ""
tags: [deploy]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Steps
1. Run tests.
2. Tag the release.
3. Deploy.
"""
    result = validate_entry(content)
    assert result.valid is True


def test_valid_decision():
    content = """\
---
id: DC-ARCH-001
type: decision
title: Use PostgreSQL for persistence
maturity: verified
category: ""
tags: [database]
created_at: "2026-01-01"
updated_at: "2026-01-01"
---

## Context
We need a reliable RDBMS.

## Decision
PostgreSQL was chosen for its JSONB support.
"""
    result = validate_entry(content)
    assert result.valid is True


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_missing_required_field():
    content = """\
---
type: pitfall
title: Missing ID
maturity: draft
tags: []
created_at: ""
updated_at: ""
---

## Symptoms
...
## Root Cause
...
## Resolution
...
"""
    result = validate_entry(content)
    assert result.valid is False
    assert any("id" in e for e in result.errors)


def test_missing_required_section():
    content = """\
---
id: PT-NET-001
type: pitfall
title: DNS Failure
maturity: draft
category: network
tags: []
created_at: ""
updated_at: ""
---

## Symptoms
DNS queries fail.

## Root Cause
Misconfigured resolver.
"""
    result = validate_entry(content)
    assert result.valid is False
    assert any("Resolution" in e for e in result.errors)


def test_invalid_type():
    content = """\
---
id: XX-001
type: unknown_type
title: Bad Type
maturity: draft
category: ""
tags: []
created_at: ""
updated_at: ""
---

Some content.
"""
    result = validate_entry(content)
    assert result.valid is False
    assert any("type" in e.lower() for e in result.errors)


def test_invalid_maturity():
    content = _make_pitfall().replace("maturity: draft", "maturity: super-verified")
    result = validate_entry(content)
    assert result.valid is False
    assert any("maturity" in e.lower() for e in result.errors)


def test_yaml_parse_error():
    content = "---\nbad: yaml: :\n---\nBody"
    result = validate_entry(content)
    assert result.valid is False


# ---------------------------------------------------------------------------
# T-COMPAT-001: entries without skill_refs still validate (TT031)
# ---------------------------------------------------------------------------


def test_compat001_no_skill_refs_valid():
    """T-COMPAT-001: complete valid entry with no skill_refs → valid=True, errors=[]."""
    result = validate_entry(_make_pitfall())
    assert result.valid is True
    assert result.errors == []


def test_compat001_explicit_empty_skill_refs_valid():
    """Empty skill_refs list is valid."""
    result = validate_entry(_make_pitfall("skill_refs: []"))
    assert result.valid is True
    assert result.errors == []


def test_compat001_skill_refs_with_valid_names():
    """skill_refs with well-formed names validates correctly."""
    result = validate_entry(_make_pitfall("skill_refs:\n  - check-redis\n  - reload-nginx"))
    assert result.valid is True
    assert result.errors == []


# ---------------------------------------------------------------------------
# 018: Expanded category tests (kubernetes, messaging, cache, monitoring)
# ---------------------------------------------------------------------------


def test_category_kubernetes_valid():
    """018: category 'kubernetes' is now valid for pitfall entries."""
    content = _make_pitfall("category: kubernetes")
    result = validate_entry(content)
    assert result.valid is True, result.errors


def test_category_monitoring_valid():
    """018: category 'monitoring' is now valid for pitfall entries."""
    content = _make_pitfall("category: monitoring")
    result = validate_entry(content)
    assert result.valid is True, result.errors


def test_category_cache_valid():
    """018: category 'cache' is now valid for pitfall entries."""
    content = _make_pitfall("category: cache")
    result = validate_entry(content)
    assert result.valid is True, result.errors


def test_category_messaging_valid():
    """018: category 'messaging' is now valid for pitfall entries."""
    content = _make_pitfall("category: messaging")
    result = validate_entry(content)
    assert result.valid is True, result.errors


def test_category_format_with_spaces_invalid():
    """Category with spaces is invalid (must be slugified)."""
    content = _make_pitfall("category: team management")
    result = validate_entry(content)
    assert result.valid is False
    assert any("category" in e.lower() for e in result.errors)


def test_category_hierarchical_valid():
    """Hierarchical categories like 'hardware/gpu' are valid."""
    content = _make_pitfall("category: hardware/gpu")
    result = validate_entry(content)
    assert result.valid is True, result.errors
