"""Find which zones touch each other and the compass direction of travel from one to the other.

    pip install shapely pandas openpyxl
    python build_zone_adjacency.py

Reads Oceanbolt_Tonnage_Map_Zones.xlsx (sheet Vertices), writes data/zone_adjacency.csv with one row per
ORDERED pair (A->B and B->A):
  from_zone_id, from_zone, to_zone_id, to_zone, relation, bearing_deg, direction, direction4
  relation   : "adjacent" (shared border) or "nested" (one zone mostly inside the other, e.g. a river/canal)
  bearing_deg: 0=N, 90=E, 180=S, 270=W, direction of travel A->B measured across the shared border
  direction  : 8-point (N, NE, E, SE, S, SW, W, NW); direction4: nearest of N/E/S/W
  For nested pairs the direction is not meaningful and is left as "nested".
"""
import math
import os

import pandas as pd
from shapely import affinity
from shapely.geometry import Point, Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(HERE, "data", "Oceanbolt_Tonnage_Map_Zones.xlsx")
OUT = os.path.join(HERE, "data", "zone_adjacency.csv")
TOUCH_DEG = 0.75   # zone edges drawn up to ~0.7 deg apart still count as touching (see shared-vertex check)
WINDOW_DEG = 8     # local window around the border used to find which way "across" points
NESTED_FRAC = 0.5  # >50% of the smaller zone inside the other = nested

PORTWATCH_CSV = os.path.join(HERE, "data", "portwatch_chokepoints.csv")
BORDER = "border at chokepoint"  # the shared zone border runs through the strait/canal (within ~1 degree)
NEAR = "border near chokepoint"  # the shared border is within ~3.5 degrees; crossing it is the usual way to transit
ROUTE = "route passes through (approximate)"  # the border is further away, but the sea route between the zones goes through
RANK = {BORDER: 0, NEAR: 1, ROUTE: 2}
# IMF PortWatch chokepoint id -> [(basis, [(zone A, zone B), ...]), ...]; a crossing between the two zones, either way,
# counts as a transit of that chokepoint. Chosen by checking where each shared border sits relative to the PortWatch
# coordinates (distances in degrees noted in dim_chokepoint.csv). A pair can serve several chokepoints.
PORTWATCH_MAP = {
    "chokepoint1": [(BORDER, [("Suez Canal", "East Med"), ("Suez Canal", "Red Sea"), ("East Med", "Red Sea")])],
    "chokepoint2": [(BORDER, [("Panama Canal", "Pacific Ocean (Central America)"),
                              ("Panama Canal", "West Atlantic Ocean (Americas)"),
                              ("Pacific Ocean (Central America)", "West Atlantic Ocean (Americas)")])],
    "chokepoint3": [(BORDER, [("Black Sea", "East Med")])],  # Bosporus; the Dardanelles are on the same border
    "chokepoint4": [(ROUTE, [("Red Sea", "West Indian Ocean"), ("Red Sea", "Persian Gulf")])],  # Gulf of Aden side
    "chokepoint5": [(NEAR, [("East Indian Ocean", "South East Asia")])],
    "chokepoint6": [(BORDER, [("Inner Persian Gulf", "Persian Gulf")])],
    "chokepoint7": [(NEAR, [("South Atlantic Ocean", "South Indian Ocean")]),
                    (ROUTE, [("Gulf of Guinea", "South Indian Ocean")])],
    "chokepoint8": [(BORDER, [("East Atlantic Ocean (Africa)", "West Med")]), (NEAR, [("Bay of Biscay", "West Med")])],
    "chokepoint10": [(ROUTE, [("Baltic Sea", "North Atlantic Ocean (Continent)")])],  # also Great Belt / Skagerrak
    "chokepoint11": [(BORDER, [("East China Sea", "South China Sea")])],
    "chokepoint12": [(BORDER, [("East China Sea", "East Sea / Sea of Japan")])],
    "chokepoint13": [(BORDER, [("East Sea / Sea of Japan", "North Pacific Ocean (Japan)")])],  # also La Perouse, Kanmon
    "chokepoint14": [(BORDER, [("North Pacific Ocean (Japan)", "South China Sea"),
                               ("North Pacific Ocean (Japan)", "South East Asia")])],
    "chokepoint15": [(BORDER, [("East Indian Ocean", "South East Asia")])],
    "chokepoint16": [(BORDER, [("South East Asia", "West Coast Australia")])],
    "chokepoint18": [(NEAR, [("East Coast Australia", "West Coast Australia"),
                             ("East Coast Australia", "South East Asia")])],
    "chokepoint19": [(BORDER, [("East Indian Ocean", "South East Asia")])],
    "chokepoint21": [(NEAR, [("East Coast South America", "South Pacific Ocean (South America)")])],  # also Cape Horn
    "chokepoint22": [(BORDER, [("Gulf of Mexico", "West Atlantic Ocean (Americas)")])],
}
# PortWatch chokepoints that cannot be seen as a crossing between two zones, and why
NOT_MAPPED = {
    "chokepoint9": "Inside the North Atlantic Ocean (Continent) zone. The nearest border (Bay of Biscay, 3 degrees away) "
                   "is crossed by general Atlantic traffic, so it cannot be attributed to Dover Strait.",
    "chokepoint17": "Inside the East China Sea zone; no zone border within 5 degrees.",
    "chokepoint20": "Inside the South East Asia zone; no zone border within 8 degrees.",
    "chokepoint23": "Both ends are inside the West Atlantic Ocean (Americas) zone; nearest border is 3.7 degrees away.",
    "chokepoint24": "Both ends are inside the West Atlantic Ocean (Americas) zone; nearest border is 5 degrees away.",
    "chokepoint25": "Inside the South East Asia zone; nearest border is 7 degrees away.",
    "chokepoint26": "Inside the North Pacific Ocean (North America) zone; nearest border is 14 degrees away.",
    "chokepoint27": "Inside the South East Asia zone; the nearest border (South China Sea) is 2.6 degrees away but mostly "
                    "carries other Philippines traffic, so it is not attributed to Mindoro Strait.",
    "chokepoint28": "Inside the Black Sea zone (Sea of Azov traffic); nearest border is 5 degrees away.",
}
ZONE_CHOKEPOINTS = {"Panama Canal": "Panama Canal", "Suez Canal": "Suez Canal"}  # zones that ARE the chokepoint


def bearing(lat1, lon1, lat2, lon2):
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    dy = lat2 - lat1
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def compass(b, n):
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] if n == 8 else ["N", "E", "S", "W"]
    step = 360 / n
    return names[int(((b + step / 2) % 360) // step)]


def portwatch():
    """PortWatch chokepoint list (portid, portname, lat, lon); ids only if the csv is not found."""
    if os.path.exists(PORTWATCH_CSV):
        return pd.read_csv(PORTWATCH_CSV)[["portid", "portname", "lat", "lon"]]
    ids = sorted(set(PORTWATCH_MAP) | set(NOT_MAPPED), key=lambda s: int(s[10:]))
    return pd.DataFrame({"portid": ids, "portname": ids, "lat": None, "lon": None})


def bridge():
    """One row per zone pair (both directions) x chokepoint: from_zone, to_zone, portwatch_id, chokepoint, basis, rank."""
    names = dict(zip(*[portwatch()[c] for c in ("portid", "portname")]))
    rows = []
    for pid, groups in PORTWATCH_MAP.items():
        for basis, pairs in groups:
            for a, b in pairs:
                for f, t in ((a, b), (b, a)):
                    rows.append(dict(from_zone=f, to_zone=t, portwatch_id=pid, chokepoint=names.get(pid, pid),
                                     basis=basis, rank=RANK[basis]))
    return pd.DataFrame(rows).sort_values(["from_zone", "to_zone", "rank", "portwatch_id"]).reset_index(drop=True)


def chokepoint_dim():
    """Dimension of all PortWatch chokepoints with their mapping status."""
    pw, br = portwatch(), bridge()
    out = []
    for r in pw.itertuples():
        mine = br[br.portwatch_id == r.portid]
        pairs = sorted({tuple(sorted(p)) for p in zip(mine.from_zone, mine.to_zone)})
        shared = sorted({c for p in pairs for c in br[(br.from_zone.isin(p)) & (br.to_zone.isin(p))
                                                      & (br.portwatch_id != r.portid)]["chokepoint"]})
        note = NOT_MAPPED.get(r.portid, "")
        if shared:
            note = "Shares its zone border with %s: crossings cannot be split between them." % ", ".join(shared)
        out.append(dict(portwatch_id=r.portid, chokepoint=r.portname, lat=r.lat, lon=r.lon,
                        mapped="Yes" if len(mine) else "No",
                        best_basis=min(mine["basis"], key=RANK.get) if len(mine) else "",
                        zone_pairs="; ".join("%s <-> %s" % p for p in pairs), note=note))
    return pd.DataFrame(out)


def build(xlsx=XLSX):
    """Return the ordered-pair adjacency table (names + Excel zone ids) for the polygons in the workbook."""
    v = pd.read_excel(xlsx, sheet_name="Vertices").sort_values(["Zone", "Vertex #"], kind="stable")
    polys, ids = {}, {}
    for z, g in v.groupby("Zone"):
        polys[z] = Polygon(zip(g["Longitude"], g["Latitude"])).buffer(0)
        ids[z] = int(g["Zone ID"].iloc[0])
    rows = []
    for a in polys:
        for b in polys:
            if a == b:
                continue
            A = polys[a]
            best = None
            for shift in (0, 360, -360):  # zones meeting across the +-180 dateline
                B = affinity.translate(polys[b], xoff=shift)
                if A.distance(B) <= TOUCH_DEG:
                    best = B
                    break
            if best is None:
                continue
            B = best
            inter = A.intersection(B).area
            small = min(A.area, B.area)
            if inter / small > NESTED_FRAC:
                rel, brg = "nested", None
            else:
                rel = "adjacent"
                border = A.buffer(TOUCH_DEG).intersection(B.buffer(TOUCH_DEG))
                p = border.centroid
                win = Point(p.x, p.y).buffer(WINDOW_DEG)
                ca, cb = A.intersection(win).centroid, B.intersection(win).centroid
                brg = bearing(ca.y, ca.x, cb.y, cb.x)
            rows.append(dict(from_zone_id=ids[a], from_zone=a, to_zone_id=ids[b], to_zone=b, relation=rel,
                             bearing_deg=None if brg is None else round(brg, 1),
                             direction="nested" if brg is None else compass(brg, 8),
                             direction4="nested" if brg is None else compass(brg, 4)))
    df = pd.DataFrame(rows).sort_values(["from_zone_id", "to_zone_id"])
    hits = {}
    for r in bridge().itertuples():  # best match first; several chokepoints can share one pair
        hits.setdefault((r.from_zone, r.to_zone), []).append((r.chokepoint, r.basis))
    keys = list(zip(df["from_zone"], df["to_zone"]))
    df["chokepoint"] = ["; ".join(n for n, _ in hits.get(k, [])) for k in keys]
    df["chokepoint_basis"] = ["; ".join(b for _, b in hits.get(k, [])) for k in keys]
    return df


def main():  # standalone: dry-only table. oceanbolt_sync_all.py builds the per-platform one itself.
    df = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    print("wrote %s: %d ordered pairs (%d adjacent, %d nested)" % (
        OUT, len(df), (df.relation == "adjacent").sum(), (df.relation == "nested").sum()))


if __name__ == "__main__":
    main()
