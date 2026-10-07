import logging

import pandas as pd
import pytest

import db
from edge import ids, store
from edge.settings import EdgeSettings
from edge.types import Adjustment, AdjustedProjection, apply_cap, cap_limit


def A(pid, delta, typ="cascade", scope="week", **kw):
    return Adjustment(pid, 2026, 5, typ, delta, "because", "test", scope=scope, **kw)


def test_cap_limit_is_percent_of_baseline_with_floor():
    assert cap_limit(20.0) == pytest.approx(7.0)                    # 35% of 20
    assert cap_limit(2.0) == pytest.approx(0.35 * 6.0)              # floor keeps low-baseline players movable
    assert cap_limit(2.0, floor=0.0) == pytest.approx(0.7)          # strict mode
    assert cap_limit(10.0, cap_pct=0.2) == pytest.approx(2.0 if 10 * 0.2 > 0.2 * 6 else 1.2)


def test_apply_cap_scales_proportionally_and_keeps_raw():
    adjs = apply_cap(10.0, [A(1, 4.0), A(1, 2.0, "vegas"), A(1, -1.0, "weather")])      # total +5, limit 3.5
    assert sum(a.delta_points for a in adjs) == pytest.approx(3.5, abs=0.02)
    assert [a.raw_delta for a in adjs] == [4.0, 2.0, -1.0]                              # uncapped values preserved
    assert adjs[0].delta_points / adjs[1].delta_points == pytest.approx(2.0, abs=0.05)  # relative sizes preserved


def test_apply_cap_leaves_small_totals_and_negative_caps_symmetric():
    small = apply_cap(15.0, [A(1, 1.0), A(1, 0.5)])
    assert [a.delta_points for a in small] == [1.0, 0.5]
    neg = apply_cap(10.0, [A(1, -6.0)])
    assert neg[0].delta_points == pytest.approx(-3.5) and neg[0].raw_delta == -6.0
    assert apply_cap(10.0, []) == []


def test_adjusted_projection_label_and_floor_at_zero():
    p = AdjustedProjection(1, 2026, 5, 12.4, [A(1, 2.5)])
    assert p.adjusted == 14.9 and p.label() == "ESPN 12.4 → Adjusted 14.9"
    assert AdjustedProjection(1, 2026, 5, 12.4).label() == "ESPN 12.4 (no adjustment)"
    assert AdjustedProjection(1, 2026, 5, 1.0, [A(1, -5.0)]).adjusted == 0.0


def test_confidence_is_validated():
    with pytest.raises(ValueError):
        Adjustment(1, 2026, 5, "vegas", 1.0, "r", "s", confidence="certain")


def test_store_roundtrip_applies_cap_and_replaces(tmp_path):
    p = str(tmp_path / "e.db")
    out = store.build_and_store({7: 10.0}, [A(7, 6.0), A(7, 3.0, "vegas"), A(7, 0.4, "weather", scope="ros")], 2026, 5, EdgeSettings(cap_pct=0.35, cap_floor=6.0), p)
    assert out[7].total == pytest.approx(3.5, abs=0.02) and out[7].adjusted == pytest.approx(13.5, abs=0.02)
    got = store.load(2026, 5, 7, p)
    assert len(got) == 3 and {a.scope for a in got} == {"week", "ros"}
    assert store.projection_for(7, 10.0, 2026, 5, p).total == pytest.approx(3.5, abs=0.02)
    store.build_and_store({7: 10.0}, [A(7, 1.0)], 2026, 5, EdgeSettings(), p)
    assert len(store.load(2026, 5, 7, p)) == 1                         # replaced, not appended
    missing = store.projection_for(99, 8.0, 2026, 5, p)
    assert missing.adjusted == 8.0 and "No edge data" in missing.note   # missing data => no adjustment, said plainly


def _frame():
    return pd.DataFrame([
        dict(mfl_id=1, gsis_id="00-0001", espn_id=111.0, sleeper_id=9001.0, pfr_id="AaaaBb00", name="Trey McBride", position="TE", team="ARI"),
        dict(mfl_id=2, gsis_id="00-0002", espn_id=None, sleeper_id=9002.0, pfr_id="CccDdd00", name="A.J. Brown", position="WR", team="PHI"),
        dict(mfl_id=3, gsis_id="00-0003", espn_id=333.0, sleeper_id=None, pfr_id=None, name="Kenneth Walker III", position="RB", team="SEA"),
    ])


def test_crosswalk_by_id_then_logged_name_fallback(tmp_path, caplog):
    p = str(tmp_path / "x.db")
    assert ids.refresh_crosswalk(p, _frame()) == 3
    assert ids.gsis_for_espn(111, p) == "00-0001" and ids.espn_for_gsis("00-0003", p) == 333 and ids.gsis_for_sleeper("9002", p) == "00-0002"
    assert ids.resolve(111, "whatever", "XXX", "TE", p) == "00-0001"                    # id match: no fallback, no warning
    with caplog.at_level(logging.WARNING, logger="edge.ids"):
        g = ids.resolve(555, "A.J. Brown", "PHI", "WR", p)                              # ESPN id unknown -> name+team+position
        assert g == "00-0002" and "name+team+position" in caplog.text
        assert ids.resolve(556, "Nobody Real", "PHI", "WR", p) is None
    assert ids.match_report(p) == {"name+team+pos": 1, "unmatched": 1}
    assert ids.resolve(557, "Kenneth Walker", "SEA", "RB", p) == "00-0003"             # suffix-insensitive normalization
