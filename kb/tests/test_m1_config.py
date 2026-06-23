"""Tests for M1: HolmesConfig.username field — set, load, default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holmes.config import HolmesConfig, load_config, save_config


class TestUsernameConfig:
    def test_default_username_is_empty(self) -> None:
        cfg = HolmesConfig()
        assert cfg.username == ""

    def test_from_dict_reads_username(self) -> None:
        cfg = HolmesConfig.from_dict({"username": "wangzhi"})
        assert cfg.username == "wangzhi"

    def test_from_dict_defaults_username_to_empty(self) -> None:
        cfg = HolmesConfig.from_dict({})
        assert cfg.username == ""

    def test_to_dict_includes_username(self) -> None:
        cfg = HolmesConfig(username="wangzhi")
        d = cfg.to_dict()
        assert d["username"] == "wangzhi"

    def test_save_and_load_username(self, tmp_path: Path) -> None:
        cfg = HolmesConfig(username="wangzhi")
        save_config(cfg, holmes_home=tmp_path)
        loaded = load_config(holmes_home=tmp_path)
        assert loaded.username == "wangzhi"

    def test_load_without_username_field(self, tmp_path: Path) -> None:
        """Config file without username field loads with empty default."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"kb_path": "/tmp/kb"}), encoding="utf-8")
        loaded = load_config(holmes_home=tmp_path)
        assert loaded.username == ""
