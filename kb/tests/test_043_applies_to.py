"""Tests for spec 043 D6 — applies_to applicability metadata (T036-T038, T040).

Covers:
- schema validation of the optional applies_to field
- load_vocabulary sources (kb-config.yml section / entry aggregation / empty)
- kb_browse applicability filtering and ranking
- doctor applicability checks (stale firmware constraints, vocabulary typos)
- end-to-end: entry with applies_to from browse to filtering
"""

from __future__ import annotations

from pathlib import Path

from holmes.kb.doctor import DoctorReport, _check_applicability
from holmes.kb.schema import validate_applies_to, validate_entry
from holmes.kb.store import list_entries
from holmes.kb.vocabulary import load_vocabulary
from holmes.mcp.tools import handle_kb_browse

from .conftest import make_entry

APPLIES_TO_FM = (
    "applies_to:\n"
    "  product_line: [serdes-gen2]\n"
    "  test_stage: [dvt]\n"
    '  firmware: "<=2.3"'
)


def _write_entry(kb_root: Path, entry_id: str, extra_frontmatter: str = "") -> Path:
    """Write a minimal valid pitfall entry (dedent-safe for multi-line extras)."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    extra = f"{extra_frontmatter}\n" if extra_frontmatter else ""
    entry_path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        "type: pitfall\n"
        f"title: Test Entry {entry_id}\n"
        "maturity: draft\n"
        "category: database\n"
        "tags: []\n"
        'created_at: "2024-01-01T00:00:00+00:00"\n'
        'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f"{extra}"
        "---\n"
        "\n"
        "## Symptoms\nTest symptoms.\n\n"
        "## Root Cause\nTest root cause.\n\n"
        "## Resolution\nTest resolution.\n",
        encoding="utf-8",
    )
    return entry_path


def _make_entry_with_applies_to(
    kb_root: Path,
    entry_id: str,
    applies_to: str = "",
) -> Path:
    """Create a pitfall entry with optional applies_to frontmatter."""
    extra = f"applies_to:\n{applies_to}" if applies_to else ""
    return _write_entry(kb_root, entry_id, extra)


# ---------------------------------------------------------------------------
# T036 — schema validation
# ---------------------------------------------------------------------------


class TestAppliesToSchema:
    def test_absent_is_valid(self):
        assert validate_applies_to(None) == []

    def test_valid_full(self):
        raw = {
            "product_line": ["serdes-gen2"],
            "test_stage": ["dvt", "evt"],
            "firmware": "<=2.3",
        }
        assert validate_applies_to(raw) == []

    def test_partial_keys_valid(self):
        assert validate_applies_to({"test_stage": ["dvt"]}) == []

    def test_unknown_key_rejected(self):
        errors = validate_applies_to({"station": ["ict"]})
        assert any("Unknown applies_to key" in e for e in errors)

    def test_not_a_mapping_rejected(self):
        errors = validate_applies_to(["serdes-gen2"])
        assert any("must be a mapping" in e for e in errors)

    def test_list_key_must_be_non_empty_list(self):
        assert validate_applies_to({"product_line": "serdes-gen2"})
        assert validate_applies_to({"product_line": []})

    def test_list_values_must_be_slugs(self):
        errors = validate_applies_to({"product_line": ["Serdes Gen2!"]})
        assert any("lowercase slug" in e for e in errors)

    def test_firmware_must_be_string(self):
        assert validate_applies_to({"firmware": ["2.3"]})
        assert validate_applies_to({"firmware": ""})

    def test_validate_entry_end_to_end(self, kb_root: Path):
        path = _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        result = validate_entry(path.read_text(encoding="utf-8"))
        assert result.valid, result.errors

    def test_validate_entry_unknown_key_invalid(self, kb_root: Path):
        path = _make_entry_with_applies_to(kb_root, "PT-DB-002", "  station: [ict]")
        result = validate_entry(path.read_text(encoding="utf-8"))
        assert not result.valid
        assert any("Unknown applies_to key" in e for e in result.errors)


# ---------------------------------------------------------------------------
# T036 — load_vocabulary sources
# ---------------------------------------------------------------------------


class TestLoadVocabulary:
    def test_from_kb_config_section(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            "vocabulary:\n"
            "  product_line: [serdes-gen2, serdes-gen3]\n"
            "  test_stage: [evt, dvt]\n",
            encoding="utf-8",
        )
        vocab = load_vocabulary(kb_root)
        assert vocab == {
            "product_line": ["serdes-gen2", "serdes-gen3"],
            "test_stage": ["dvt", "evt"],
        }

    def test_aggregated_from_entries(self, kb_root: Path):
        _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        _make_entry_with_applies_to(kb_root, "PT-DB-002", "  product_line: [serdes-gen3]")
        vocab = load_vocabulary(kb_root)
        assert vocab == {
            "product_line": ["serdes-gen2", "serdes-gen3"],
            "test_stage": ["dvt"],
        }

    def test_config_section_wins_over_entries(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            "vocabulary:\n  product_line: [from-config]\n",
            encoding="utf-8",
        )
        _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        vocab = load_vocabulary(kb_root)
        assert vocab == {"product_line": ["from-config"]}

    def test_empty_when_no_sources(self, kb_root: Path):
        make_entry(kb_root)  # entry without applies_to
        assert load_vocabulary(kb_root) == {}

    def test_missing_config_file(self, kb_root: Path):
        assert load_vocabulary(kb_root) == {}


# ---------------------------------------------------------------------------
# T037 — kb_browse applicability filtering
# ---------------------------------------------------------------------------


class TestBrowseApplicability:
    def _setup(self, kb_root: Path):
        """One universal entry, one serdes-gen2 entry, one serdes-gen3 entry."""
        make_entry(kb_root, entry_id="PT-DB-001")  # universal
        _write_entry(kb_root, "PT-DB-002", APPLIES_TO_FM)
        _make_entry_with_applies_to(kb_root, "PT-DB-003", "  product_line: [serdes-gen3]")

    def test_entries_carry_applies_to(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(kb_root)
        by_id = {e["id"]: e for e in result["entries"]}
        assert by_id["PT-DB-001"]["applies_to"] == {}
        assert by_id["PT-DB-002"]["applies_to"]["product_line"] == ["serdes-gen2"]

    def test_filter_ranks_matches_first_keeps_rest(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(kb_root, product_line="serdes-gen2")
        ids = [e["id"] for e in result["entries"]]
        # Universal + matching come first (relative order among them kept),
        # the non-matching serdes-gen3 entry sinks to the end but stays.
        assert ids[-1] == "PT-DB-003"
        assert set(ids[:2]) == {"PT-DB-001", "PT-DB-002"}
        assert result["total"] == 3

    def test_strict_filter_excludes_non_matching(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(kb_root, product_line="serdes-gen2", strict=True)
        ids = {e["id"] for e in result["entries"]}
        assert ids == {"PT-DB-001", "PT-DB-002"}
        assert result["total"] == 2

    def test_multi_dimensional_filter_requires_all(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(
            kb_root, product_line="serdes-gen2", test_stage="pvt", strict=True
        )
        # PT-DB-002 matches product_line but not test_stage → only universal stays.
        ids = {e["id"] for e in result["entries"]}
        assert ids == {"PT-DB-001"}

    def test_no_filter_params_unchanged_order(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(kb_root)
        assert result["total"] == 3

    def test_guide_mentions_vocabulary(self, kb_root: Path):
        self._setup(kb_root)
        result = handle_kb_browse(kb_root)
        assert "serdes-gen2" in result["guide"]
        assert "product_line=" in result["guide"]


# ---------------------------------------------------------------------------
# T038 — doctor applicability checks
# ---------------------------------------------------------------------------


def _run_applicability(kb_root: Path, verbose: bool = True) -> DoctorReport:
    report = DoctorReport()
    _check_applicability(kb_root, list_entries(kb_root), verbose, report)
    return report


class TestDoctorApplicability:
    def test_stale_firmware_reported(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            'current_context:\n  serdes-gen2_firmware: "3.0"\n',
            encoding="utf-8",
        )
        _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)  # firmware: <=2.3
        report = _run_applicability(kb_root)
        warns = [i for i in report.items if i.category == "applicability" and i.level == "warn"]
        assert any("适用性疑似过期" in i.message for i in warns)

    def test_satisfied_constraint_not_reported(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            'current_context:\n  serdes-gen2_firmware: "2.1"\n',
            encoding="utf-8",
        )
        _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        report = _run_applicability(kb_root)
        oks = [i for i in report.items if i.category == "applicability" and i.level == "ok"]
        assert len(oks) == 1

    def test_unparseable_constraint_skipped(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            'current_context:\n  serdes-gen2_firmware: "3.0"\n',
            encoding="utf-8",
        )
        _make_entry_with_applies_to(kb_root, "PT-DB-001", '  firmware: "latest-beta"')
        report = _run_applicability(kb_root)
        warns = [i for i in report.items if i.category == "applicability" and i.level == "warn"]
        # "latest-beta" is a bare string → plain equality vs "3.0" → conflict reported.
        assert any("适用性疑似过期" in i.message for i in warns)

        # An unparseable <= constraint is skipped instead.
        (kb_root / "pitfall" / "database" / "PT-DB-001.md").unlink()
        _make_entry_with_applies_to(kb_root, "PT-DB-002", '  firmware: "<=beta"')
        report = _run_applicability(kb_root)
        assert not [
            i for i in report.items
            if i.category == "applicability" and i.level == "warn"
        ]

    def test_context_key_scoped_to_product_line(self, kb_root: Path):
        """serdes-gen2_firmware must not flag entries of another product line."""
        (kb_root / "kb-config.yml").write_text(
            'current_context:\n  serdes-gen2_firmware: "3.0"\n',
            encoding="utf-8",
        )
        _make_entry_with_applies_to(
            kb_root, "PT-DB-001", "  product_line: [serdes-gen3]\n  firmware: '<=2.3'"
        )
        report = _run_applicability(kb_root)
        assert not [
            i for i in report.items
            if i.category == "applicability" and i.level == "warn"
        ]

    def test_vocabulary_typo_reported_with_closest(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            "vocabulary:\n  product_line: [serdes-gen2]\n",
            encoding="utf-8",
        )
        _make_entry_with_applies_to(kb_root, "PT-DB-001", "  product_line: [serdes_gen2]")
        report = _run_applicability(kb_root)
        warns = [i for i in report.items if i.category == "applicability" and i.level == "warn"]
        assert any("疑似笔误" in i.message and "serdes-gen2" in i.message for i in warns)

    def test_no_applies_to_no_findings(self, kb_root: Path):
        make_entry(kb_root)
        report = _run_applicability(kb_root)
        oks = [i for i in report.items if i.category == "applicability" and i.level == "ok"]
        assert len(oks) == 1

    def test_summary_item_when_not_verbose(self, kb_root: Path):
        (kb_root / "kb-config.yml").write_text(
            'current_context:\n  serdes-gen2_firmware: "3.0"\n',
            encoding="utf-8",
        )
        _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        report = _run_applicability(kb_root, verbose=False)
        warns = [i for i in report.items if i.category == "applicability" and i.level == "warn"]
        assert len(warns) == 1
        assert "--verbose" in warns[0].message


# ---------------------------------------------------------------------------
# T040 — end-to-end: entry with applies_to from browse to filtering
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_browse_filter_flow(self, kb_root: Path):
        """Entry carrying applies_to is validated, browsable, and filterable."""
        # 1. Entry passes schema validation with applies_to.
        path = _write_entry(kb_root, "PT-DB-001", APPLIES_TO_FM)
        assert validate_entry(path.read_text(encoding="utf-8")).valid

        # 2. Vocabulary self-accumulates from the entry.
        assert load_vocabulary(kb_root)["product_line"] == ["serdes-gen2"]

        # 3. Browse returns it with applies_to and the guide advertises the vocab.
        result = handle_kb_browse(kb_root)
        entry = result["entries"][0]
        assert entry["applies_to"]["firmware"] == "<=2.3"
        assert "serdes-gen2" in result["guide"]

        # 4. Filtering by its product line keeps it; another line sinks/excludes it.
        match = handle_kb_browse(kb_root, product_line="serdes-gen2", strict=True)
        assert [e["id"] for e in match["entries"]] == ["PT-DB-001"]
        miss = handle_kb_browse(kb_root, product_line="serdes-gen9")
        assert miss["entries"][0]["id"] == "PT-DB-001"  # still returned, demoted
        miss_strict = handle_kb_browse(kb_root, product_line="serdes-gen9", strict=True)
        assert miss_strict["entries"] == []

        # 5. Doctor stays quiet when no current_context conflicts exist.
        report = _run_applicability(kb_root)
        assert report.warn_count == 0
