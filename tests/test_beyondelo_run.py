"""beyondELO run end to end on tiny invented inputs: pull, reconcile, write, read back."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import beyondelo_helpers as h
from fpl import beyondelo as run_mod
from fpl.beyondelo_api import BeyondEloError, Client, Settings
from fpl.beyondelo_build import OUT_COLUMNS, BuildError

SEASONS = ["2025-2026", "2026-2027"]


def season_records(season: str) -> list[dict]:
    recs = h.records()[:4]  # the fifth is a match we lack; it would exceed our fixture count
    if season == "2026-2027":
        for r in recs:
            r["date"] = r["date"].replace("2025", "2026")
            r["season"] = season
    return recs


def make_root(tmp_path, aliases=None):
    """A root with processed tables, previous teams files and a config."""
    for s in SEASONS:
        folder = tmp_path / "data" / "processed" / s
        folder.mkdir(parents=True)
        h.dim_team().to_parquet(folder / "dim_team.parquet", index=False)
        fx = h.fixture().assign(season=s)
        if s == "2026-2027":
            fx["kickoff_utc"] = fx["kickoff_utc"].str.replace("2025", "2026")
        fx.to_parquet(folder / "fact_fixture.parquet", index=False)
    data = tmp_path / "up" / "data"
    (data / "2024-2025" / "teams").mkdir(parents=True)
    pd.DataFrame({"code": [10, 11, 12], "name": ["a", "b", "c"]}).to_csv(
        data / "2024-2025" / "teams" / "teams.csv", index=False)
    (data / "2025-2026").mkdir()
    pd.DataFrame({"code": [10, 11, 12, 13], "name": ["a", "b", "c", "d"]}).to_csv(
        data / "2025-2026" / "teams.csv", index=False)
    return {
        "upstream": {"checkout_path": "up", "data_dir": "data"},
        "paths": {"processed_dir": "data/processed"}, "premier_league_tag": "prem",
        "beyondelo": {
            "base_url": "https://example.test/v1", "seasons": SEASONS, "per_page": 100,
            "max_requests": 20, "min_seconds_between_requests": 6.5, "timeout_seconds": 5,
            "external_dir": "data/external/beyondelo", "club_aliases": aliases or {},
            "max_wrong_direction_share": 0.5,
        },
    }


def serve(url: str):
    if "competitions" in url:
        return h.ok(json.loads((h.FIXTURES / "competitions.json").read_text()))
    season = url.split("season=")[1].split("&")[0]
    recs = season_records(season)
    return h.ok(h.page(recs, len(recs)))


def client_for(root, transport, env=None) -> Client:
    ft = h.FakeTime()
    s = Settings("https://example.test/v1", 100, 20, 6.5, 5, root / "data/external/beyondelo/raw")
    env = {"BEYONDELO_API_KEY": "k"} if env is None else env
    return Client(s, transport, ft.clock, ft.sleep, env)


def test_run_writes_tables_reconciliation_and_reader_round_trips(tmp_path):
    cfg = make_root(tmp_path)
    t = h.FakeTransport(handler=serve)
    paths = run_mod.run(cfg, tmp_path, client_for(tmp_path, t))
    assert len(t.calls) == 3
    out = tmp_path / "data/external/beyondelo"
    assert set(paths) == set(SEASONS) and (out / "2025-2026.parquet").exists()
    first = run_mod.load_beyondelo("2025-2026", out)
    assert list(first.columns) == OUT_COLUMNS and len(first) == 6
    assert set(first.loc[first.promoted, "team_id"]) == {4}
    second = run_mod.load_beyondelo("2026-2027", out)
    assert not second.promoted.any() and (second.season == "2026-2027").all()
    recon = pd.read_csv(out / "reconciliation.csv")
    assert set(recon.season) == set(SEASONS) and recon.matches.sum() > 0
    pd.testing.assert_frame_equal(first, pd.read_parquet(out / "2025-2026.parquet"))


def test_rerun_from_cache_alone_needs_no_key_and_no_request(tmp_path):
    cfg = make_root(tmp_path)
    run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=serve)))
    t = h.FakeTransport()
    run_mod.run(cfg, tmp_path, client_for(tmp_path, t, env={}))
    assert t.calls == []


def test_unmapped_names_fail_for_every_season_then_aliases_fix_it_from_the_cache(tmp_path):
    cfg = make_root(tmp_path)

    def renamed(url: str):
        status, hdr, body = serve(url)
        return status, hdr, body.replace(b'"Alpha"', b'"Alpha FC"').replace(b'"Beta"', b'"Beta FC"')

    with pytest.raises(BuildError, match="Alpha FC.*Beta FC"):
        run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=renamed)))
    out = tmp_path / "data/external/beyondelo"
    assert not (out / "2025-2026.parquet").exists() and not (out / "reconciliation.csv").exists()
    cfg["beyondelo"]["club_aliases"] = {"Alpha FC": "Alpha", "Beta FC": "Beta"}
    t = h.FakeTransport()
    run_mod.run(cfg, tmp_path, client_for(tmp_path, t, env={}))
    assert t.calls == [] and (out / "2025-2026.parquet").exists()


def test_unmapped_names_in_different_seasons_are_listed_together(tmp_path):
    cfg = make_root(tmp_path)

    def renamed(url: str):
        status, hdr, body = serve(url)
        old, new = (b'"Alpha"', b'"Alpha FC"') if "2025-2026" in url else (b'"Beta"', b'"Beta FC"')
        return status, hdr, body.replace(old, new)

    with pytest.raises(BuildError, match=r"\['Alpha FC', 'Beta FC'\]"):
        run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=renamed)))


def test_missing_partner_names_the_cache_files_to_delete(tmp_path):
    cfg = make_root(tmp_path)

    def behind(url: str):
        status, hdr, body = serve(url)
        data = json.loads(body)
        if "season=2025-2026" in url:
            data["data"] = data["data"][1:]
            data["meta"]["total"] -= 1
        return h.ok(data)

    with pytest.raises(BuildError, match=r"without a beyondELO partner.*delete .*"
                                         r"matches_2025-2026_p\*\.json"):
        run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=behind)))


def test_other_build_failures_carry_no_refresh_hint(tmp_path):
    cfg = make_root(tmp_path)

    def swapped(url: str):
        status, hdr, body = serve(url)
        data = json.loads(body)
        for r in data["data"] if "season=" in url else []:
            r["home_elo_before"], r["home_elo_after"] = r["home_elo_after"], r["home_elo_before"]
            r["away_elo_before"], r["away_elo_after"] = r["away_elo_after"], r["away_elo_before"]
        return h.ok(data)

    def missing_field(url: str):
        status, hdr, body = serve(url)
        data = json.loads(body)
        for r in data["data"] if "season=" in url else []:
            del r["home_elo_after"]
        return h.ok(data)

    for handler, text in ((swapped, "wrong way"), (missing_field, "home_elo_after")):
        with pytest.raises(BuildError, match=text) as exc:
            run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=handler)))
        assert "delete" not in str(exc.value)
        for f in (tmp_path / "data/external/beyondelo/raw").glob("matches_*"):
            f.unlink()


def test_a_total_above_our_fixture_count_stops_after_page_one(tmp_path):
    cfg = make_root(tmp_path)

    def too_many(url: str):
        status, hdr, body = serve(url)
        if "season=" not in url:
            return status, hdr, body
        return h.ok(h.page(h.records(), 5))  # five matches, we hold four fixtures

    t = h.FakeTransport(handler=too_many)
    with pytest.raises(BeyondEloError, match="filters may have been ignored"):
        run_mod.run(cfg, tmp_path, client_for(tmp_path, t))
    assert len(t.calls) == 2


def test_failed_reconciliation_writes_nothing(tmp_path):
    cfg = make_root(tmp_path)

    def wrong_score(url: str):
        status, hdr, body = serve(url)
        data = json.loads(body)
        if "season=2026-2027" in url:
            data["data"][0]["home_score"] = 9
        return h.ok(data)

    with pytest.raises(BuildError, match="score") as exc:
        run_mod.run(cfg, tmp_path, client_for(tmp_path, h.FakeTransport(handler=wrong_score)))
    assert "delete" not in str(exc.value)
    assert not list((tmp_path / "data/external/beyondelo").glob("*.parquet"))


def test_missing_processed_table_fails_before_any_request(tmp_path):
    cfg = make_root(tmp_path)
    (tmp_path / "data/processed/2026-2027/fact_fixture.parquet").unlink()
    t = h.FakeTransport(handler=serve)
    with pytest.raises(BuildError, match="fact_fixture"):
        run_mod.run(cfg, tmp_path, client_for(tmp_path, t))
    assert t.calls == []


def test_previous_codes_read_either_layout_and_fail_when_absent(tmp_path):
    cfg = make_root(tmp_path)
    data = tmp_path / "up" / "data"
    assert run_mod.read_previous_codes(data, "2025-2026") == {10, 11, 12}
    assert run_mod.read_previous_codes(data, "2026-2027") == {10, 11, 12, 13}
    with pytest.raises(BuildError, match="2023-2024"):
        run_mod.read_previous_codes(data, "2024-2025")
    assert cfg["beyondelo"]["seasons"] == SEASONS


def test_empty_previous_teams_file_fails(tmp_path):
    make_root(tmp_path)
    data = tmp_path / "up" / "data"
    pd.DataFrame({"code": []}).to_csv(data / "2025-2026" / "teams.csv", index=False)
    with pytest.raises(BuildError, match="no usable club codes"):
        run_mod.read_previous_codes(data, "2026-2027")


def test_reader_default_directory_comes_from_config(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text(
        "beyondelo:\n  external_dir: somewhere/else\n", encoding="utf-8")
    folder = tmp_path / "somewhere" / "else"
    folder.mkdir(parents=True)
    pd.DataFrame({c: [] for c in OUT_COLUMNS}).to_parquet(folder / "2025-2026.parquet")
    monkeypatch.setattr(run_mod, "ROOT", tmp_path)
    assert list(run_mod.load_beyondelo("2025-2026").columns) == OUT_COLUMNS


def test_usage_line_never_shows_the_key_on_the_command_line():
    assert "BEYONDELO_API_KEY=" not in run_mod.__doc__


def test_reader_rejects_missing_file_and_wrong_columns(tmp_path):
    with pytest.raises(FileNotFoundError, match="fpl.beyondelo"):
        run_mod.load_beyondelo("2025-2026", tmp_path)
    pd.DataFrame({"team_id": [1]}).to_parquet(tmp_path / "2025-2026.parquet")
    with pytest.raises(ValueError, match="columns"):
        run_mod.load_beyondelo("2025-2026", tmp_path)


def test_settings_from_config_and_main(tmp_path, monkeypatch):
    cfg = make_root(tmp_path)
    s = run_mod.settings_from(cfg["beyondelo"], tmp_path)
    assert (s.max_requests, s.min_seconds, s.per_page) == (20, 6.5, 100)
    assert s.raw_dir == tmp_path / "data/external/beyondelo/raw"
    seen = {}

    def fake_run(c: dict) -> dict:
        seen["cfg"] = c
        return {"2025-2026": tmp_path}

    monkeypatch.setattr(run_mod, "run", fake_run)
    run_mod.main(["--config", str(run_mod.ROOT / "config" / "pipeline.yaml")])
    assert seen["cfg"]["beyondelo"]["max_requests"] == 20


def test_real_config_section_is_complete():
    cfg = run_mod.load_config(run_mod.ROOT / "config" / "pipeline.yaml")["beyondelo"]
    assert cfg["base_url"].startswith("https://") and cfg["max_requests"] == 20
    assert cfg["seasons"] == SEASONS and cfg["per_page"] == 100 and cfg["club_aliases"] == {}
    assert cfg["max_wrong_direction_share"] == 0.5
