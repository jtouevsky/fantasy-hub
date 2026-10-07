import pytest

import demo_data
import market as mk
from market import Market, soft
from season import Season
from strategy import Strategy
from valuation import ValueModel


def build():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
    for p in fas:
        p.bye_week = 0
    s = Season(snap, ValueModel(snap, fas), Strategy(), fas)
    return snap, fas, s


def test_soft_is_order_preserving_positive_and_never_zero():
    xs = [-30, -5, 0, 1, 1.9, 2, 3, 40]
    ys = [soft(x) for x in xs]
    assert ys == sorted(ys) and all(y > 0 for y in ys) and soft(40) == 40 and soft(2) == 2


def test_market_keeps_an_injured_star_valued_while_my_value_drops():
    snap, fas, s = build()
    wr = sorted((p for t in snap.teams for p in t.roster if p.position == "WR"), key=lambda p: -s.healthy_par(p))
    star, other = wr[0], wr[6]
    for i, p in enumerate(wr):
        p.market = {"ros_pos_rank": i + 1.0, "auction": 40.0 - i, "adp": 10.0 + i, "ppr_rank": 10.0 + i, "started": 90.0 - i}
    healthy = Market(s, [p for t in snap.teams for p in t.roster] + fas).value(star)
    star.injury_status = "INJURY_RESERVE"
    s2 = Season(snap, ValueModel(snap, fas), Strategy(), fas)
    m2 = Market(s2, [p for t in snap.teams for p in t.roster] + fas)
    assert m2.value(star) > 0.8 * healthy                                      # the market still rates him highly (consensus rank, auction, ADP)
    assert s2.par(star) < 0.7 * s2.healthy_par(star)                           # ...my value discounts the missed weeks
    assert m2.value(star) > m2.value(other)


def test_value_scale_is_shared_and_ordering_follows_market_signals():
    snap, fas, s = build()
    rbs = sorted((p for t in snap.teams for p in t.roster if p.position == "RB"), key=lambda p: -s.healthy_par(p))
    for i, p in enumerate(rbs):
        p.market = {"ros_pos_rank": i + 1.0, "auction": 50.0 - i, "adp": 5.0 + i}
        p.games_played = 0                                                    # production is a deliberate 15% of the blend; switch it off to test the market signals alone
    m = Market(s, [p for t in snap.teams for p in t.roster] + fas)
    vals = [m.value(p) for p in rbs]
    assert vals == sorted(vals, reverse=True)
    top = max(s.healthy_par(p) for t in snap.teams for p in t.roster)
    assert vals[0] <= top + 1e-6 and vals[-1] >= min(s.healthy_par(p) for t in snap.teams for p in t.roster) - 1e-6      # same points scale as my value


def test_missing_market_data_falls_back_to_production_then_to_my_value_and_says_so():
    snap, fas, s = build()
    m = Market(s, [p for t in snap.teams for p in t.roster] + fas)
    p = snap.my_team.roster[0]
    p.market = {}
    row = Market(s, [p]).row(p)
    assert not row.has_market and row.components.keys() <= {"production"}


def test_consolidation_premium_makes_one_star_worth_more_than_the_sum_of_two_mid_players():
    snap, fas, s = build()
    m = Market(s, [p for t in snap.teams for p in t.roster] + fas)
    star = m.v_elite * 1.5
    mid = star / 2
    assert m.worth(star) > 2 * m.worth(mid) * 0.999 or m.worth(star) > m.worth(mid) * 2
    assert m.worth(star) > star and m.worth(5.0) > 5.0 and m.worth(-3.0) > 0       # premium; negatives are softened, not clipped to 0


def test_brand_is_market_minus_production():
    snap, fas, s = build()
    p = max((q for t in snap.teams for q in t.roster if q.position == "WR"), key=lambda q: s.healthy_par(q))
    p.market = {"ros_pos_rank": 1.0, "auction": 60.0, "adp": 1.0}
    p.total_points, p.games_played = 20.0, 4                                      # 5 ppg: reputation >> results
    row = Market(s, [q for t in snap.teams for q in t.roster] + fas).row(p)
    assert row.brand > 0 and row.has_market
