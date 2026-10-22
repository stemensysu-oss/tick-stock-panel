from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.api import settings as settings_api
from app.services import preferences


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(preferences, "_path", lambda: path)
    preferences._invalidate_cache()
    yield path
    preferences._invalidate_cache()


def test_old_preferences_preserve_current_content_appearance(isolated_preferences):
    isolated_preferences.write_text('{"screener_auto_run": false}', encoding="utf-8")
    assert preferences.get_content_typography() == {
        "content_font_size": 18,
        "content_font_family": "default",
    }


@pytest.mark.parametrize(
    ("size", "family", "expected_size", "expected_family"),
    [
        (1, "system", 14, "system"),
        (99, "pingfang", 22, "pingfang"),
        (True, "url(https://invalid/font)", 18, "default"),
        ("22", None, 18, "default"),
        (None, ["system"], 18, "default"),
    ],
)
def test_invalid_stored_typography_is_safe(
    isolated_preferences, size, family, expected_size, expected_family,
):
    isolated_preferences.write_text(json.dumps({
        "content_font_size": size, "content_font_family": family,
    }), encoding="utf-8")
    assert preferences.get_content_typography() == {
        "content_font_size": expected_size, "content_font_family": expected_family,
    }


def test_api_save_survives_cache_restart_and_reset_preserves_other_settings(isolated_preferences):
    preferences.save({"nav_hidden": ["/data"], "realtime_quote_interval": 6.0})
    result = settings_api.update_content_typography(settings_api.ContentTypographyPrefs(
        content_font_size=22, content_font_family="microsoft-yahei",
    ))
    assert result == {"content_font_size": 22, "content_font_family": "microsoft-yahei"}
    preferences._invalidate_cache()
    assert preferences.get_content_typography() == result
    settings_api.update_content_typography(settings_api.ContentTypographyPrefs(
        content_font_size=18, content_font_family="default",
    ))
    preferences._invalidate_cache()
    assert preferences.get_content_typography()["content_font_size"] == 18
    assert preferences.load()["nav_hidden"] == ["/data"]
    assert preferences.load()["realtime_quote_interval"] == 6.0


@pytest.mark.parametrize("payload", [
    {"content_font_size": 13, "content_font_family": "default"},
    {"content_font_size": 23, "content_font_family": "default"},
    {"content_font_size": True, "content_font_family": "system"},
    {"content_font_size": "18", "content_font_family": "system"},
    {"content_font_size": 18.5, "content_font_family": "system"},
    {"content_font_size": 18, "content_font_family": "custom-css"},
    {"content_font_size": 18, "content_font_family": "system", "nav_size": 99},
])
def test_api_rejects_invalid_or_unknown_fields(payload):
    with pytest.raises(ValidationError):
        settings_api.ContentTypographyPrefs.model_validate(payload)
