import strategy
from strategy import Strategy

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1}


def test_defaults_match_the_requested_rules():
    s = Strategy()
    assert s.stream_dst and not s.stream_k and s.stream_swap_gain == 2.0 and s.recent_days == 7 and s.playoff_weight == 1.5 and s.explanation == "Short"
    assert s.streaming == {"D/ST"}
    caps = s.caps(SLOTS)
    assert caps == {"QB": 2, "D/ST": 1, "K": 0, "TE": 2}          # no K slot in this league -> never add a kicker; TE: 1 starter + 1 extra


def test_caps_scale_with_superflex_and_kickers():
    sf = Strategy().caps({"QB": 1, "OP": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "D/ST": 1})
    assert sf["QB"] == 3 and sf["K"] == 1                          # 2 QB-capable starters -> cap is starters + 1
    assert Strategy(stream_k=True).streaming == {"D/ST", "K"}


def test_settings_persist_and_ignore_unknown_keys(tmp_path):
    p = str(tmp_path / "s.db")
    assert strategy.load(p) == Strategy()
    strategy.save(Strategy(stream_dst=False, stream_swap_gain=3.5, explanation="Beginner", max_qb=3), p)
    got = strategy.load(p)
    assert not got.stream_dst and got.stream_swap_gain == 3.5 and got.explanation == "Beginner" and got.max_qb == 3
    import db
    db.setting_set("strategy", '{"stream_dst": false, "bogus_future_key": 1}', p)
    assert strategy.load(p).stream_dst is False


def test_prompt_block_states_the_rules():
    txt = strategy.prompt_block(Strategy(), SLOTS, 5)
    assert "week 5" in txt and "D/ST" in txt and "QB <= 2" in txt and "swap only if this-week gain >= 2" in txt and "no definitions" in txt
    assert "define terms" in strategy.prompt_block(Strategy(explanation="Beginner"), SLOTS, 5)
