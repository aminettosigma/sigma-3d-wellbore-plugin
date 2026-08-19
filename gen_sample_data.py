#!/usr/bin/env python3
"""Generate the two CSVs this plugin expects, for uploading to Sigma as demo data.

  python3 gen_sample_data.py            # writes sample_data/*.csv

well_surveys.csv   — one row per survey station (the trajectory + completion data)
formation_grid.csv — one row per grid node per formation (the heat-mapped surface)
"""
import csv, math, os, random

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
FORMS = ["WCA", "AVU", "SBL"]
WELLS = ["MID-A1H", "MID-A2H", "MID-A3H", "MID-B1H", "MID-B2H", "MID-B3H",
         "MID-C1H", "MID-C2H", "MID-C3H", "MID-C4H"]
PADS = ["Bravo 12"] * 3 + ["Delta 7"] * 3 + ["Echo 3"] * 4
PAD_XY = [(402000, 406500)] * 3 + [(404800, 409200)] * 3 + [(407200, 411500)] * 4


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def surveys(rnd):
    rows = []
    for w, name in enumerate(WELLS):
        pad_x, pad_y = PAD_XY[w]
        offset = (w % 3 - 1) * 660 + (660 if w > 8 else 0)
        azi = math.radians(12 if w < 3 else 358 if w < 6 else 6)
        kop = 6200 + rnd.random() * 400            # kick-off point, ft MD
        landing = 9100 + rnd.random() * 500        # landing-zone TVD
        lateral = 8200 + rnd.random() * 2400
        form = FORMS[w % 3]
        md = tvd = inc = 0.0
        x = pad_x + offset * math.cos(azi)
        y = pad_y + offset * math.sin(azi)
        stage, next_stage = 0, 0.0
        while md < kop + 2200 + lateral:
            md += 100
            target = 0.0 if md < kop else min(90.0, (md - kop) / 2200 * 90)
            build = (target - inc) * 0.55 + (rnd.random() - 0.5) * 1.1
            inc = clamp(inc + build, 0, 92)
            r = math.radians(inc)
            tvd += 100 * math.cos(r)
            x += 100 * math.sin(r) * math.sin(azi + (rnd.random() - 0.5) * 0.03)
            y += 100 * math.sin(r) * math.cos(azi + (rnd.random() - 0.5) * 0.03)
            dls = abs(build) + rnd.random() * 0.35
            is_lat = inc > 87
            is_stage = False
            if is_lat and md >= next_stage:
                stage += 1
                next_stage = md + 200
                is_stage = True
            rows.append({
                "WELL_NAME": name, "PAD": PADS[w], "TARGET_FORMATION": form,
                "MD_FT": round(md), "EASTING_FT": round(x, 1), "NORTHING_FT": round(y, 1),
                "TVD_FT": round(tvd, 1), "INCLINATION_DEG": round(inc, 2),
                "AZIMUTH_DEG": round(math.degrees(azi) % 360, 2),
                "DOGLEG_SEVERITY_DEG_100FT": round(dls, 2),
                "BUILD_RATE_DEG_100FT": round(build, 3),
                "ROP_FT_HR": round((62 + rnd.random() * 38) if is_lat else (24 + rnd.random() * 26), 1),
                "WOB_KLB": round(18 + rnd.random() * 22, 1),
                "FRAC_STAGE": stage if is_stage else "",
                "PROPPANT_LBS": round(340000 + rnd.random() * 260000) if is_stage else "",
                "FLUID_BBL": round(8200 + rnd.random() * 3600) if is_stage else "",
                "ISIP_PSI": round(6100 + rnd.random() * 1400) if is_stage else "",
            })
            if tvd > landing + 60 and inc > 89:
                inc = 90.0
    return rows


def grid(rnd):
    rows = []
    for f, form in enumerate(FORMS):
        base = 8600 + f * 620
        for i in range(13):
            for j in range(13):
                rows.append({
                    "FORMATION": form,
                    "EASTING_FT": 400500 + i * 700,
                    "NORTHING_FT": 405200 + j * 620,
                    "TOP_TVD_FT": round(base + 140 * math.sin(i / 3.1) + 95 * math.cos(j / 2.6) + rnd.random() * 30),
                    "AVG_BUILD_RATE_DEG_100FT": round(0.18 * math.sin(i / 2.4 + f) + 0.13 * math.cos(j / 3.2)
                                                      + (rnd.random() - 0.5) * 0.05, 3),
                    "AVG_POROSITY_PCT": round(6.5 + 2.2 * math.sin(i / 4.0) + rnd.random() * 0.8, 2),
                })
    return rows


def write(path, rows):
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"{path}  ({len(rows)} rows)")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rnd = random.Random(97)
    write(os.path.join(OUT, "well_surveys.csv"), surveys(rnd))
    write(os.path.join(OUT, "formation_grid.csv"), grid(rnd))
