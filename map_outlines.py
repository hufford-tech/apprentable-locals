"""Project US Atlas state arcs into the finder's offline SVG coordinates.

The source is us-atlas 3.0.1 states-10m.json, derived from US Census Bureau
cartographic boundaries and distributed under the ISC license. Shared TopoJSON
arcs are drawn once; arcs used by one state form the national outline.
"""

import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "raw/maps/us_atlas_states_10m.json"
RAD = math.pi / 180


def albers(lat, lon, phi1, phi2, phi0, lam0):
    n = (math.sin(phi1 * RAD) + math.sin(phi2 * RAD)) / 2
    c = math.cos(phi1 * RAD) ** 2 + 2 * n * math.sin(phi1 * RAD)
    rho0 = math.sqrt(c - 2 * n * math.sin(phi0 * RAD)) / n
    rho = math.sqrt(c - 2 * n * math.sin(lat * RAD)) / n
    theta = n * (lon - lam0) * RAD
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def project(lat, lon, state_id):
    if state_id == "02":
        if lon > 0:  # Aleutian islands cross the 180th meridian.
            lon -= 360
        x, y = albers(lat, lon, 55, 65, 60, -152)
        return 145 + x * 520, 505 - y * 520
    if state_id == "15":
        x, y = albers(lat, lon, 19, 22, 20.5, -157)
        return 330 + x * 760, 545 - y * 760
    x, y = albers(lat, lon, 29.5, 45.5, 37.5, -96)
    return 487 + x * 1150, 291 - y * 1150


def simplify(points, tolerance=0.45):
    """Keep coast shape at map scale while reducing embedded HTML size."""
    if len(points) <= 2:
        return points
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    tol2 = tolerance * tolerance
    while stack:
        start, end = stack.pop()
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        farthest, index = -1, None
        for i in range(start + 1, end):
            x, y = points[i]
            t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / length2)) if length2 else 0
            dist2 = (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2
            if dist2 > farthest:
                farthest, index = dist2, i
        if farthest > tol2:
            keep.add(index)
            stack.extend(((start, index), (index, end)))
    return [points[i] for i in sorted(keep)]


def svg_number(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


@lru_cache(maxsize=1)
def outline_paths():
    topo = json.loads(SOURCE.read_text(encoding="utf-8"))
    scale = topo["transform"]["scale"]
    translate = topo["transform"]["translate"]
    counts = Counter()
    owners = {}
    for state in topo["objects"]["states"]["geometries"]:
        state_id = state["id"]
        if int(state_id) >= 60:  # exclude territories outside the map insets
            continue
        polygons = [state["arcs"]] if state["type"] == "Polygon" else state["arcs"]
        for polygon in polygons:
            for ring in polygon:
                for signed_index in ring:
                    index = signed_index if signed_index >= 0 else ~signed_index
                    counts[index] += 1
                    owners.setdefault(index, state_id)

    def path_for_arc(index):
        x = y = 0
        points = []
        for dx, dy in topo["arcs"][index]:
            x += dx
            y += dy
            lon = x * scale[0] + translate[0]
            lat = y * scale[1] + translate[1]
            points.append(project(lat, lon, owners[index]))
        points = simplify(points)
        if len(points) < 2:
            return ""
        return "M" + "L".join(f"{svg_number(px)},{svg_number(py)}" for px, py in points)

    arcs = {index: path_for_arc(index) for index in counts}
    return {
        "states": "".join(arcs[index] for index in sorted(counts)),
        "nation": "".join(arcs[index] for index in sorted(counts) if counts[index] == 1),
    }


if __name__ == "__main__":
    paths = outline_paths()
    print(f"State paths: {len(paths['states']):,} chars; national outline: {len(paths['nation']):,} chars")
