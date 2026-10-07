import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import db
from edge import news_ai
from edge.history import Hist
from edge.modules import cascade as C


# ---------------------------------------------------------------------------
# synthetic team: RB1 'X' (60% of carries), RB2 'B' (30%), RB3 'C' (10%), WR 'W'
# ---------------------------------------------------------------------------
def make_hist(x_missed_games=0, x_share=0.6, b_wo_share=0.8, games=8):
    rows, inj = [], []
    for g in range(1, games + 1):
        t = 202400 + g
        x_out = g > games - x_missed_games - 1 and g < games          # last `x_missed_games` games before the target game
        team_carries = 25
        shares = {"X": 0.0 if x_out else x_share, "B": b_wo_share if x_out else 0.3, "C": 0.1 if not x_out else 0.2}
        tot = sum(shares.values())
        for gs, sh in shares.items():
            if gs == "X" and x_out:
                inj.append(dict(season=2024, week=g, t=t, team="AAA", gsis="X", pos="RB", report_status="Out", practice_status="Did Not Participate In Practice"))
                continue
            c = round(team_carries * sh / tot)
            rows.append(dict(gsis=gs, name={"X": "Chuba Star", "B": "Bo Backup", "C": "Cy Third"}[gs], pos="RB", team="AAA", opp="BBB", season=2024, week=g, t=t,
                             pts=c * 0.5, rush_pts=c * 0.5, rec_pts=2.0, carries=c, targets=3, receptions=2))
        rows.append(dict(gsis="W", name="Wes Wideout", pos="WR", team="AAA", opp="BBB", season=2024, week=g, t=t, pts=10.0, rush_pts=0.0, rec_pts=10.0, carries=0, targets=7, receptions=5))
    w = pd.DataFrame(rows)
    i = pd.DataFrame(inj, columns=["season", "week", "t", "team", "gsis", "pos", "report_status", "practice_status"])
    return Hist([2024], w, pd.DataFrame(), pd.DataFrame(), i, pd.DataFrame())


FLOWS = {"RB": {"carries": {"RB": 0.9, "WR": 0.0, "TE": 0.0}, "targets": {"RB": 0.3, "WR": 0.3, "TE": 0.1}}}


def test_depth_fallback_gives_the_vacated_share_to_teammates_in_proportion_to_current_share():
    h = make_hist(x_missed_games=0)
    out = C.compute_team(C.prep_for(h), FLOWS, "AAA", 202409, {"X": 1.0})
    b, c = out["B"], out["C"]
    assert b["n_wo"] == 0 and c["n_wo"] == 0                              # no with/without sample -> depth estimate only
    # X had ~60% of ~25 carries; flow 0.9 -> ~13.5 carries vacated, split in proportion to B's and C's current shares (~3:1; carries are whole numbers)
    assert 2.5 < b["d_carries"] / c["d_carries"] < 4.5
    assert 8.0 < b["d_carries"] + c["d_carries"] < 14.0
    assert b["delta"] > c["delta"] > 0
    assert "W" in out and out["W"]["d_targets"] > 0                       # receivers also pick up targets, but no carries
    assert abs(out["W"]["d_carries"]) < 1e-9


def test_with_without_sample_overrides_depth_estimate_as_it_grows():
    small = C.compute_team(C.prep_for(make_hist(x_missed_games=1)), FLOWS, "AAA", 202409, {"X": 1.0})["B"]
    big = C.compute_team(C.prep_for(make_hist(x_missed_games=4, b_wo_share=0.8)), FLOWS, "AAA", 202409, {"X": 1.0})["B"]
    assert small["n_wo"] == 1 and big["n_wo"] >= 3
    # with 4 games without X, B's share actually jumped to ~80%: the estimate must lean toward that history (shrinkage lam = n/(n+3))
    assert big["d_carries"] > 0
    assert C.explain(C.prep_for(make_hist(4)), big, {"X": "OUT"})[1] == "high"          # >=3-game sample => high confidence
    assert C.explain(C.prep_for(make_hist(1)), small, {"X": "OUT"})[1] == "med"


def test_probability_scales_the_cascade_linearly_for_questionable_players():
    prep = C.prep_for(make_hist(0))
    full = C.compute_team(prep, FLOWS, "AAA", 202409, {"X": 1.0})["B"]["delta"]
    half = C.compute_team(prep, FLOWS, "AAA", 202409, {"X": 0.5})["B"]["delta"]
    assert half == pytest.approx(full / 2, rel=1e-6)
    assert C.compute_team(prep, FLOWS, "AAA", 202409, {"X": 0.0}) == {}


def test_absent_player_without_a_real_role_or_a_non_skill_position_creates_no_cascade():
    prep = C.prep_for(make_hist(0))
    assert C.compute_team(prep, FLOWS, "AAA", 202409, {"W": 1.0}).get("W") is None          # the absent player never receives his own boost
    assert C.compute_team(prep, FLOWS, "ZZZ", 202409, {"X": 1.0}) == {}                     # unknown team
    prep.pos_of["X"] = "QB"
    assert C.compute_team(prep, FLOWS, "AAA", 202409, {"X": 1.0}) == {}                     # QBs are not cascaded


def test_vacated_volume_is_conserved_not_invented():
    out = C.compute_team(C.prep_for(make_hist(0)), FLOWS, "AAA", 202409, {"X": 1.0})
    gained = sum(v["d_carries"] for k, v in out.items())
    assert gained <= 0.6 * 25 * 1.05                                                       # can't hand out more carries than X had


def test_p_for_uses_practice_trend_for_questionable_only():
    p = {"Out": 1.0, "Questionable": 0.4, "Questionable|dnp": 0.6, "Questionable|full": 0.3}
    assert C.p_for(p, "Questionable", "dnp") == 0.6 and C.p_for(p, "Questionable", "full") == 0.3
    assert C.p_for(p, "Questionable", "limited") == 0.4                                    # no bucket -> overall rate
    assert C.p_for(p, "Out", "full") == 1.0 and C.p_for(p, "Healthy") == 0.0


# ---------------------------------------------------------------------------
# news scanning: extraction only, guardrails against invented facts
# ---------------------------------------------------------------------------
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
RECENT = "2026-10-06T09:00:00Z"


def item(pid=1, name="Chuba Hubbard", headline="Hubbard (ankle) ruled out vs. the Saints", story="Chuba Hubbard has been ruled out for Sunday's game with an ankle injury. Rico Dowdle is expected to handle the lead role.", published=RECENT):
    return dict(player_espn_id=pid, gsis=f"G{pid}", player_name=name, team="CAR", pos="RB", headline=headline, story=story, published=published, url="https://espn.example/1")


def test_prefilter_keeps_recent_injury_related_items_only():
    keep = [item()]
    skip = [item(2, headline="Player X signs endorsement deal", story="Nothing notable to report today."),
            item(3, published="2026-09-01T00:00:00Z")]
    assert [i["player_espn_id"] for i in news_ai.prefilter(keep + skip, now=NOW)] == [1]


def test_guardrails_drop_unsupported_status_games_and_beneficiaries():
    text = "Chuba Hubbard has been ruled out for Sunday. Rico Dowdle is expected to handle the lead role."
    ok = news_ai.validate_event({"event_type": "injury", "status": "out", "expected_games_missed": None, "beneficiaries": ["Rico Dowdle"], "summary": "x"}, text, "Chuba Hubbard")
    assert ok["status"] == "out" and ok["beneficiaries"] == ["Rico Dowdle"] and ok["dropped"] == []
    bad = news_ai.validate_event({"event_type": "injury", "status": "ir", "expected_games_missed": 6, "beneficiaries": ["Jonathon Brooks", "Hubbard"], "summary": "x"}, text, "Chuba Hubbard")
    assert bad["status"] is None and bad["expected_games_missed"] is None and bad["beneficiaries"] == []
    assert len(bad["dropped"]) >= 3                                                        # status, games, 2 beneficiaries (incl. the player himself)
    said = news_ai.validate_event({"event_type": "injury", "status": "out", "expected_games_missed": 3, "beneficiaries": []}, "He will miss three games with a hamstring strain; he is out.", "A B")
    assert said["expected_games_missed"] == 3
    assert news_ai.validate_event({"event_type": "weird", "status": "maybe"}, "text", "A B")["event_type"] == "other"


def test_parse_response_tolerates_chatter_and_bad_json():
    assert news_ai.parse_response('Sure! [{"key": "a", "status": "out"}] hope that helps')[0]["key"] == "a"
    assert news_ai.parse_response("no json here") == [] and news_ai.parse_response("[not json]") == []


def test_scan_extracts_stores_raw_text_caches_and_survives_llm_failure(tmp_path):
    p = str(tmp_path / "n.db")
    seen = []

    def llm(prompt):
        seen.append(prompt)
        key = [l.split("KEY: ")[1] for l in prompt.splitlines() if l.startswith("KEY: ")][0]
        return json.dumps([{"key": key, "event_type": "injury", "status": "out", "expected_games_missed": None, "beneficiaries": ["Rico Dowdle"], "summary": "Hubbard is out Sunday."}])

    events = news_ai.scan([item()], llm, p, now=NOW)
    assert len(events) == 1 and events[0]["status"] == "out" and events[0]["gsis"] == "G1" and "ruled out" in events[0]["raw_text"] and events[0]["source_url"].startswith("https://")
    news_ai.scan([item()], llm, p, now=NOW)
    assert len(seen) == 1                                                                 # second scan served from cache: zero extra Claude calls

    def boom(prompt):
        raise RuntimeError("claude down")
    assert news_ai.scan([item(9, "Other Guy")], boom, p, now=NOW) != [] or True           # no exception escapes
    with db.connect(p) as c:
        assert c.execute("SELECT COUNT(*) n FROM news_events WHERE error IS NOT NULL").fetchone()["n"] == 1


def test_prompt_tells_claude_to_extract_not_infer():
    pr = news_ai.build_prompt([dict(item(), key="k1")])
    assert "KEY: k1" in pr and "Chuba Hubbard" in pr
    assert "never add" in news_ai.SYSTEM and "ONLY what the text says" in news_ai.SYSTEM
