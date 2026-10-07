import league_client as lc

ROW = {"player": {"id": 4262921, "fullName": "A.J. Brown",
                  "ownership": {"averageDraftPosition": 46.3, "auctionValueAverage": 25.35, "percentOwned": 94.96, "percentStarted": 8.99},
                  "draftRanksByRankType": {"PPR": {"rank": 20}},
                  "rankings": {"0": [{"rankType": "PPR", "rank": 10, "rankSourceId": 9}, {"rankType": "STANDARD", "averageRank": 11.0}, {"rankType": "PPR", "averageRank": 10.0}]}}}


def test_parse_market_reads_consensus_signals_and_skips_missing_fields():
    m = lc.parse_market([ROW, {"player": {"id": 7}}, {"player": {"id": 9, "ownership": {"percentOwned": 3.0}}}, {"nope": 1}])
    assert m[4262921] == {"adp": 46.3, "auction": 25.35, "owned": 94.96, "started": 8.99, "ppr_rank": 20.0, "ros_pos_rank": 10.0}   # PPR averageRank preferred
    assert 7 not in m and m[9] == {"owned": 3.0}                                                                                  # nothing invented


def test_ros_rank_falls_back_to_any_average_rank():
    row = {"player": {"id": 1, "rankings": {"0": [{"rankType": "STANDARD", "averageRank": 22.0}]}}}
    assert lc.parse_market([row])[1]["ros_pos_rank"] == 22.0
