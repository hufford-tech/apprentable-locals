import csv

with open("out/jurisdictions.csv", encoding="utf-8") as f:
    j_rows = list(csv.DictReader(f))

inside_rows = [r for r in j_rows if r["jurisdiction_type"] == "I"]


def pct_to_float(p):
    p = (p or "").strip().rstrip("%")
    try:
        return float(p)
    except ValueError:
        return None


with open("out/scrape_targets.csv", encoding="utf-8") as f:
    targets = list(csv.DictReader(f))

old_pop_served = {}   # lu -> population served using 2000 figures (as originally computed)
new_pop_served = {}   # lu -> population served using current Census figures

for t in targets:
    lu = t["lu_number"]
    old_total = 0.0
    new_total = 0.0
    for r in inside_rows:
        if r["lu_number"] != lu:
            continue
        p = pct_to_float(r["percentage"])
        weight = (p / 100.0) if p is not None else 1.0

        try:
            pop2000 = float(r["population_2000"]) if r["population_2000"].strip() else None
        except ValueError:
            pop2000 = None
        if pop2000 is not None:
            old_total += pop2000 * weight

        try:
            pop_cur = float(r["population_current"]) if r["population_current"].strip() else None
        except ValueError:
            pop_cur = None
        if pop_cur is not None:
            new_total += pop_cur * weight

    old_pop_served[lu] = old_total
    new_pop_served[lu] = new_total

old_rank = {lu: i + 1 for i, lu in enumerate(
    sorted(old_pop_served, key=lambda x: -old_pop_served[x])
)}
new_rank = {lu: i + 1 for i, lu in enumerate(
    sorted(new_pop_served, key=lambda x: -new_pop_served[x])
)}

rows_out = []
for t in targets:
    lu = t["lu_number"]
    row = dict(t)
    row["population_2000_served_inside"] = f"{old_pop_served[lu]:.0f}"
    row["population_current_served_inside"] = f"{new_pop_served[lu]:.0f}"
    pop2000 = old_pop_served[lu]
    popcur = new_pop_served[lu]
    row["pct_change_served"] = f"{100.0*(popcur-pop2000)/pop2000:.1f}" if pop2000 else ""
    row["rank_2000"] = old_rank[lu]
    row["rank_current"] = new_rank[lu]
    row["rank_change"] = old_rank[lu] - new_rank[lu]  # positive = moved up (better rank / lower number now)
    rows_out.append(row)

rows_out.sort(key=lambda r: -float(r["population_current_served_inside"]))

fieldnames = list(targets[0].keys()) + [
    "population_2000_served_inside", "population_current_served_inside", "pct_change_served",
    "rank_2000", "rank_current", "rank_change",
]
with open("out/targets_with_population.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows_out)

print(f"Wrote out/targets_with_population.csv: {len(rows_out)} rows")
print()
print("=== Top 40 by current weighted population ===")
for r in rows_out[:40]:
    print(f'  #{r["rank_current"]:3} LU{r["lu_number"]:6} {r["charter_city"]:20}{r["charter_state"]:4} '
          f'current={float(r["population_current_served_inside"]):>12,.0f}  2000={float(r["population_2000_served_inside"]):>12,.0f}  '
          f'chg={r["pct_change_served"]:>6}%  rank_change={r["rank_change"]:+d}')

print()
print("=== 20 locals whose rank moved UP the most (rank_change positive & largest) ===")
up_movers = sorted(rows_out, key=lambda r: -r["rank_change"])[:20]
for r in up_movers:
    print(f'  LU{r["lu_number"]:6} {r["charter_city"]:20}{r["charter_state"]:4} rank {r["rank_2000"]:>3} -> {r["rank_current"]:>3}  '
          f'(change {r["rank_change"]:+d})  current_pop={float(r["population_current_served_inside"]):>12,.0f}')

print()
print("=== 20 locals whose rank moved DOWN the most ===")
down_movers = sorted(rows_out, key=lambda r: r["rank_change"])[:20]
for r in down_movers:
    print(f'  LU{r["lu_number"]:6} {r["charter_city"]:20}{r["charter_state"]:4} rank {r["rank_2000"]:>3} -> {r["rank_current"]:>3}  '
          f'(change {r["rank_change"]:+d})  current_pop={float(r["population_current_served_inside"]):>12,.0f}')
