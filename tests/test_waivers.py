import demo_data
from valuation import ValueModel
from waivers import rank_free_agents, suggest_add_drops


def _setup():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    return snap, fas, ValueModel(snap, fas)


def test_obvious_upgrade_is_suggested_and_drop_is_a_bench_player():
    snap, fas, model = _setup()
    me = snap.my_team
    starter_k = next(p for p in me.roster if p.position == "K")
    star = max((p for p in fas if p.position == "K"), key=lambda p: p.week_proj)
    star.week_proj, star.season_proj_ppg = starter_k.week_proj + 6, starter_k.season_proj_ppg + 6
    out = suggest_add_drops(snap, model, fas)
    adds = [r for r in out if r.add.player_id == star.player_id]
    assert adds and adds[0].weekly_gain > 0
    bench_ids = {p.player_id for p in me.roster if p.lineup_slot == "BE"}
    assert all(r.drop.player_id in bench_ids or r.drop.position == "K" for r in out)
    assert "ESPN app" in adds[0].action()


def test_no_more_than_two_suggestions_per_position_and_sorted():
    snap, fas, model = _setup()
    out = suggest_add_drops(snap, model, fas, max_suggestions=20)
    assert all(sum(1 for r in out if r.add.position == pos) <= 2 for pos in {r.add.position for r in out})
    assert [r.score for r in out] == sorted((r.score for r in out), reverse=True)


def test_rank_free_agents_values_nonnegative():
    snap, fas, model = _setup()
    ranks = rank_free_agents(model, fas)
    assert len(ranks) == len(fas) and all(r.ros_value >= 0 and r.week_value >= 0 for r in ranks)
