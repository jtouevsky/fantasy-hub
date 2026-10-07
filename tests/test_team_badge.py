import assets
import ui


def test_logo_transform_centers_artwork_and_normalizes_size_for_every_team():
    geo = assets.logo_geometry()
    assert len(geo) == 32
    for abbr, (cx, cy, w, h) in geo.items():
        dx, dy, k = assets.logo_transform((cx, cy, w, h))
        assert abs(0.5 + k * (cx - 0.5) + dx / 100 - 0.5) < 0.003, abbr          # artwork centered horizontally
        assert abs(0.5 + k * (cy - 0.5) + dy / 100 - 0.5) < 0.003, abbr          # ...and vertically
        assert abs(k * max(w, h) - assets.FIT) < 0.003, abbr                     # longest side = same share of the badge


def test_every_team_uses_one_small_uniform_logo_file():
    for abbr in assets.nfl_teams():
        url = assets.team_logo(abbr)
        assert "scoreboard" in url and f"w={assets.LOGO_PX}" in url


def test_badge_markup_fixed_size_ring_and_fallback():
    b = ui.Brand(None)
    url = assets.team_logo("JAX")
    b.ok[url] = True
    good = b.team_badge("JAX", 44)
    assert 'class="tbadge"' in good and "--s:44px" in good and 'width="44" height="44"' in good and "--dx" in good and "Jacksonville" in good
    b.ok[url] = False
    bad = b.team_badge("JAX", 44)
    assert "tbadge fb" in bad and "<img" not in bad and "JAX" in bad                # neutral abbreviation fallback
    assert b.team_badge("JAX", 18) != b.team_badge("JAX", 44) and "--s:18px" in b.team_badge("JAX", 18)
