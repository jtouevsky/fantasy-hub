"""Smoke-test your .env against ESPN. Prints league structure only - never secrets.

    python check_connection.py
"""
from config import load_config
from league_client import LeagueClient, LeagueConnectionError, get_snapshot


def main() -> None:
    cfg = load_config()
    print(cfg)  # Config.__repr__ masks secrets
    try:
        client = LeagueClient(cfg)
        snap = get_snapshot(client, force=True)
    except LeagueConnectionError as e:
        raise SystemExit(f"FAILED: {e}")
    me = snap.my_team
    print(f"OK  league='{snap.league_name}' year={snap.year} week={snap.week} teams={snap.team_count}")
    print(f"    starters={snap.starter_slots} bench={snap.bench_slots} ir={snap.ir_slots}")
    print(f"    scoring={snap.scoring_notes}")
    print(f"    my team: {me.name} ({me.record}), {len(me.roster)} players, owner label: {me.owner_label!r}")
    print("    owners:", ", ".join(f"{t.team_id}:{t.owners[0].first_name if t.owners else '?'}" for t in snap.teams))
    m = snap.matchup_for(me.team_id)
    print(f"    matchup this week: {m}")
    if client.last_warning:
        print("    WARNING:", client.last_warning)
    sample = [p for p in me.roster][:3]
    for p in sample:
        print(f"    {p.name:24s} {p.position:5s} slot={p.lineup_slot:5s} status={p.injury_status:12s} "
              f"wk_proj={p.week_proj:5.1f} ppg={p.actual_ppg:5.1f} proj_ppg={p.season_proj_ppg:5.1f} bye={p.bye_week}")


if __name__ == "__main__":
    main()
