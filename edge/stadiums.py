"""Stadium table: location + roof type. Domes and retractable roofs get NO weather adjustment (we can't know if a retractable roof is open)."""
from __future__ import annotations

# team -> (stadium, lat, lon, roof)   roof: 'outdoor' | 'dome' | 'retractable'
STADIUMS: dict[str, tuple[str, float, float, str]] = {
    "ARI": ("State Farm Stadium", 33.5276, -112.2626, "retractable"), "ATL": ("Mercedes-Benz Stadium", 33.7554, -84.4009, "retractable"),
    "BAL": ("M&T Bank Stadium", 39.2780, -76.6227, "outdoor"), "BUF": ("Highmark Stadium", 42.7738, -78.7870, "outdoor"),
    "CAR": ("Bank of America Stadium", 35.2258, -80.8528, "outdoor"), "CHI": ("Soldier Field", 41.8623, -87.6167, "outdoor"),
    "CIN": ("Paycor Stadium", 39.0955, -84.5161, "outdoor"), "CLE": ("Huntington Bank Field", 41.5061, -81.6995, "outdoor"),
    "DAL": ("AT&T Stadium", 32.7473, -97.0945, "retractable"), "DEN": ("Empower Field at Mile High", 39.7439, -105.0201, "outdoor"),
    "DET": ("Ford Field", 42.3400, -83.0456, "dome"), "GB": ("Lambeau Field", 44.5013, -88.0622, "outdoor"),
    "HOU": ("NRG Stadium", 29.6847, -95.4107, "retractable"), "IND": ("Lucas Oil Stadium", 39.7601, -86.1639, "retractable"),
    "JAX": ("EverBank Stadium", 30.3239, -81.6373, "outdoor"), "KC": ("GEHA Field at Arrowhead", 39.0489, -94.4839, "outdoor"),
    "LV": ("Allegiant Stadium", 36.0909, -115.1833, "dome"), "LAC": ("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "LAR": ("SoFi Stadium", 33.9535, -118.3392, "dome"), "MIA": ("Hard Rock Stadium", 25.9580, -80.2389, "outdoor"),
    "MIN": ("U.S. Bank Stadium", 44.9735, -93.2575, "dome"), "NE": ("Gillette Stadium", 42.0909, -71.2643, "outdoor"),
    "NO": ("Caesars Superdome", 29.9511, -90.0812, "dome"), "NYG": ("MetLife Stadium", 40.8135, -74.0745, "outdoor"),
    "NYJ": ("MetLife Stadium", 40.8135, -74.0745, "outdoor"), "PHI": ("Lincoln Financial Field", 39.9008, -75.1675, "outdoor"),
    "PIT": ("Acrisure Stadium", 40.4468, -80.0158, "outdoor"), "SF": ("Levi's Stadium", 37.4030, -121.9700, "outdoor"),
    "SEA": ("Lumen Field", 47.5952, -122.3316, "outdoor"), "TB": ("Raymond James Stadium", 27.9759, -82.5033, "outdoor"),
    "TEN": ("Nissan Stadium", 36.1665, -86.7713, "outdoor"), "WSH": ("Northwest Stadium", 38.9076, -76.8645, "outdoor"),
}
# neutral-site stadiums that show up in the schedule (matched by name)
NEUTRAL: dict[str, tuple[float, float, str]] = {
    "Tottenham Hotspur Stadium": (51.6043, -0.0663, "outdoor"), "Wembley Stadium": (51.5560, -0.2796, "outdoor"),
    "Allianz Arena": (48.2188, 11.6247, "outdoor"), "Deutsche Bank Park": (50.0686, 8.6455, "outdoor"),
    "Estadio Azteca": (19.3029, -99.1505, "outdoor"), "Santiago Bernabéu": (40.4531, -3.6883, "outdoor"),
    "Maracanã": (-22.9121, -43.2302, "outdoor"), "Croke Park": (53.3609, -6.2514, "outdoor"),
}


def locate(home_team: str, stadium_name: str | None = None) -> tuple[float, float, str, str] | None:
    """(lat, lon, roof, stadium) for a game: a named neutral site wins, otherwise the home team's stadium."""
    if stadium_name and stadium_name in NEUTRAL:
        lat, lon, roof = NEUTRAL[stadium_name]
        return lat, lon, roof, stadium_name
    s = STADIUMS.get(home_team)
    return (s[1], s[2], s[3], s[0]) if s else None
