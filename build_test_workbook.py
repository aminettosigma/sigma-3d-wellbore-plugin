#!/usr/bin/env python3
"""Build a Sigma workbook that exercises the 3D Well & Completion Viewer plugin.

All data is generated in-warehouse with Snowflake generators — no source tables
needed, so this runs against any Snowflake connection.

  python3 build_test_workbook.py <BASE_URL> <TOKEN> <CONNECTION_ID> [PLUGIN_ID] [FOLDER_ID]
  python3 build_test_workbook.py ... --update <WORKBOOK_ID>
"""
import json, os, sys, urllib.request, urllib.error

args = [a for a in sys.argv[1:] if not a.startswith("--")]
UPDATE = None
if "--update" in sys.argv:
    UPDATE = sys.argv[sys.argv.index("--update") + 1]
    args = [a for a in args if a != UPDATE]
BASE, TOKEN, CONN = args[0], args[1], args[2]
PLUGIN = args[3] if len(args) > 3 else "858d442f-5602-4299-a5f1-33b046e59183"
FOLDER = args[4] if len(args) > 4 else None
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

INK = "#16324F"; SLATE = "#5A6B7B"; LINE = "#DCE3EA"; CARD = {
    "backgroundColor": "#FFFFFF", "borderColor": LINE, "borderWidth": 1, "borderRadius": "round"}
NUM0 = {"kind": "number", "formatString": ",.0f"}
NUM2 = {"kind": "number", "formatString": ",.2f"}
NUM3 = {"kind": "number", "formatString": ",.3f"}

# ---------------------------------------------------------------- synthetic wells
# 10 horizontal wells on 3 pads. Inclination is a closed-form function of MD
# (vertical → build through 2,200 ft → 90° lateral), so TVD/E/N are running sums.
WELLS = [
    # name,        pad,        formation, pad_E,  pad_N,  offset, azi, kop,  lateral
    ("MID-A1H", "Bravo 12", "WCA", 402000, 406500, -660, 12,  6200,  8600),
    ("MID-A2H", "Bravo 12", "AVU", 402000, 406500,    0, 12,  6320,  9400),
    ("MID-A3H", "Bravo 12", "SBL", 402000, 406500,  660, 12,  6180, 10200),
    ("MID-B1H", "Delta 7",  "WCA", 404800, 409200, -660, 358, 6450,  9800),
    ("MID-B2H", "Delta 7",  "AVU", 404800, 409200,    0, 358, 6280,  8900),
    ("MID-B3H", "Delta 7",  "SBL", 404800, 409200,  660, 358, 6520, 10500),
    ("MID-C1H", "Echo 3",   "WCA", 407200, 411500, -990, 6,   6210,  9100),
    ("MID-C2H", "Echo 3",   "AVU", 407200, 411500, -330, 6,   6380, 10000),
    ("MID-C3H", "Echo 3",   "SBL", 407200, 411500,  330, 6,   6260,  8400),
    ("MID-C4H", "Echo 3",   "WCA", 407200, 411500,  990, 6,   6440,  9600),
]
VALS = ",".join(
    f"('{n}','{p}','{f}',{e},{no},{o},{a},{k},{l})" for n, p, f, e, no, o, a, k, l in WELLS)

WIN = ("PARTITION BY WELL_NAME ORDER BY MD_FT "
       "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")
TRAJ = f"""WITH w AS (
  SELECT column1::string AS WELL_NAME, column2::string AS PAD, column3::string AS TARGET_FORMATION,
         column4 AS PAD_E, column5 AS PAD_N, column6 AS OFFSET_FT,
         column7 AS AZI_DEG, column8 AS KOP_FT, column9 AS LATERAL_FT
  FROM (VALUES {VALS})
), g AS (SELECT SEQ4() + 1 AS n FROM TABLE(GENERATOR(ROWCOUNT => 400))
), st AS (
  SELECT w.*, g.n, g.n * 100 AS MD_FT
  FROM w JOIN g ON g.n * 100 <= w.KOP_FT + 2200 + w.LATERAL_FT
), i AS (
  SELECT st.*, LEAST(90, GREATEST(0, (MD_FT - KOP_FT) / 2200.0 * 90)) AS INC_DEG FROM st
), c AS (
  SELECT i.*,
    SUM(100 * COS(RADIANS(INC_DEG))) OVER ({WIN}) AS TVD_FT,
    PAD_E + OFFSET_FT * COS(RADIANS(AZI_DEG))
      + SUM(100 * SIN(RADIANS(INC_DEG)) * SIN(RADIANS(AZI_DEG))) OVER ({WIN}) AS EASTING_FT,
    PAD_N + OFFSET_FT * SIN(RADIANS(AZI_DEG))
      + SUM(100 * SIN(RADIANS(INC_DEG)) * COS(RADIANS(AZI_DEG))) OVER ({WIN}) AS NORTHING_FT,
    COALESCE(LAG(INC_DEG) OVER (PARTITION BY WELL_NAME ORDER BY MD_FT), 0) AS PREV_INC
  FROM i
), s AS (
  SELECT c.*,
    INC_DEG - PREV_INC AS BUILD_RATE,
    (INC_DEG >= 89.4 AND MOD(n, 2) = 0) AS IS_STAGE
  FROM c
), t AS (
  SELECT s.*,
    CASE WHEN IS_STAGE THEN SUM(IFF(IS_STAGE, 1, 0)) OVER ({WIN}) END AS FRAC_STAGE
  FROM s
)"""

SURVEY_SQL = TRAJ + """
SELECT WELL_NAME, PAD, TARGET_FORMATION, MD_FT,
  ROUND(EASTING_FT, 1) AS EASTING_FT, ROUND(NORTHING_FT, 1) AS NORTHING_FT,
  ROUND(TVD_FT, 1) AS TVD_FT, ROUND(INC_DEG, 2) AS INCLINATION_DEG, AZI_DEG AS AZIMUTH_DEG,
  ROUND(ABS(BUILD_RATE) + 0.30 * ABS(SIN(MD_FT / 690.0)), 2) AS DOGLEG_SEVERITY,
  ROUND(BUILD_RATE, 3) AS BUILD_RATE,
  ROUND(IFF(INC_DEG > 87, 62 + 30 * ABS(SIN(MD_FT / 430.0)),
                          24 + 22 * ABS(COS(MD_FT / 510.0))), 1) AS ROP_FT_HR,
  ROUND(18 + 22 * ABS(SIN(MD_FT / 880.0)), 1) AS WOB_KLB,
  FRAC_STAGE,
  IFF(IS_STAGE, ROUND(340000 + 260000 * ABS(SIN(MD_FT / 311.0))), NULL) AS PROPPANT_LBS,
  IFF(IS_STAGE, ROUND(8200 + 3600 * ABS(COS(MD_FT / 407.0))), NULL) AS FLUID_BBL,
  IFF(IS_STAGE, ROUND(6100 + 1400 * ABS(SIN(MD_FT / 233.0))), NULL) AS ISIP_PSI
FROM t ORDER BY WELL_NAME, MD_FT"""

STAGE_SQL = TRAJ + """
SELECT WELL_NAME, PAD, TARGET_FORMATION, FRAC_STAGE, MD_FT,
  ROUND(TVD_FT, 1) AS TVD_FT,
  ROUND(340000 + 260000 * ABS(SIN(MD_FT / 311.0))) AS PROPPANT_LBS,
  ROUND(8200 + 3600 * ABS(COS(MD_FT / 407.0))) AS FLUID_BBL,
  ROUND(6100 + 1400 * ABS(SIN(MD_FT / 233.0))) AS ISIP_PSI
FROM t WHERE IS_STAGE ORDER BY WELL_NAME, FRAC_STAGE"""

GRID_SQL = """WITH f AS (
  SELECT column1::string AS FORMATION, column2 AS BASE_TVD, column3 AS PHASE
  FROM (VALUES ('WCA', 8600, 0), ('AVU', 9240, 1), ('SBL', 9880, 2))
), g AS (SELECT SEQ4() AS s FROM TABLE(GENERATOR(ROWCOUNT => 169))
), c AS (SELECT FLOOR(s / 13) AS i, MOD(s, 13) AS j FROM g)
SELECT f.FORMATION,
  400500 + c.i * 700 AS EASTING_FT,
  405200 + c.j * 620 AS NORTHING_FT,
  ROUND(f.BASE_TVD + 140 * SIN(c.i / 3.1 + f.PHASE) + 95 * COS(c.j / 2.6)) AS TOP_TVD_FT,
  ROUND(0.18 * SIN(c.i / 2.4 + f.PHASE) + 0.13 * COS(c.j / 3.2), 3) AS AVG_BUILD_RATE,
  ROUND(6.5 + 2.2 * SIN(c.i / 4.0) + 0.4 * COS(c.j / 3.0), 2) AS AVG_POROSITY_PCT
FROM f CROSS JOIN c"""

def sqlcols(prefix, spec):
    return [{"id": prefix + cid, "formula": f"[Custom SQL/{col}]", "name": nm,
             **({"format": fmt} if fmt else {})} for cid, col, nm, fmt in spec]

SURVEY_COLS = [
    ("well", "WELL_NAME", "Well", None), ("pad", "PAD", "Pad", None),
    ("form", "TARGET_FORMATION", "Target Formation", None),
    ("md", "MD_FT", "MD (ft)", NUM0), ("e", "EASTING_FT", "Easting (ft)", NUM0),
    ("n", "NORTHING_FT", "Northing (ft)", NUM0), ("tvd", "TVD_FT", "TVD (ft)", NUM0),
    ("inc", "INCLINATION_DEG", "Inclination (°)", NUM2),
    ("dls", "DOGLEG_SEVERITY", "Dogleg Severity (°/100ft)", NUM2),
    ("br", "BUILD_RATE", "Build Rate (°/100ft)", NUM3),
    ("rop", "ROP_FT_HR", "ROP (ft/hr)", NUM2), ("wob", "WOB_KLB", "WOB (klb)", NUM2),
    ("stage", "FRAC_STAGE", "Frac Stage", None),
    ("prop", "PROPPANT_LBS", "Proppant (lbs)", NUM0),
    ("fluid", "FLUID_BBL", "Fluid (bbl)", NUM0), ("isip", "ISIP_PSI", "ISIP (psi)", NUM0),
]
STAGE_COLS = [
    ("well", "WELL_NAME", "Well", None), ("pad", "PAD", "Pad", None),
    ("form", "TARGET_FORMATION", "Target Formation", None),
    ("no", "FRAC_STAGE", "Stage", None), ("md", "MD_FT", "MD (ft)", NUM0),
    ("tvd", "TVD_FT", "TVD (ft)", NUM0), ("prop", "PROPPANT_LBS", "Proppant (lbs)", NUM0),
    ("fluid", "FLUID_BBL", "Fluid (bbl)", NUM0), ("isip", "ISIP_PSI", "ISIP (psi)", NUM0),
]
GRID_COLS = [
    ("form", "FORMATION", "Formation", None), ("e", "EASTING_FT", "Easting (ft)", NUM0),
    ("n", "NORTHING_FT", "Northing (ft)", NUM0), ("tvd", "TOP_TVD_FT", "Top TVD (ft)", NUM0),
    ("build", "AVG_BUILD_RATE", "Avg Build Rate (°/100ft)", NUM3),
    ("por", "AVG_POROSITY_PCT", "Avg Porosity (%)", NUM2),
]

surveys = {"id": "surveys", "kind": "table", "name": "Well Surveys", "visibleAsSource": True,
           "source": {"connectionId": CONN, "kind": "sql", "statement": SURVEY_SQL},
           "columns": sqlcols("s-", SURVEY_COLS), "order": ["s-" + c[0] for c in SURVEY_COLS],
           "style": dict(CARD)}
stages = {"id": "stages", "kind": "table", "name": "Completion Stages", "visibleAsSource": True,
          "source": {"connectionId": CONN, "kind": "sql", "statement": STAGE_SQL},
          "columns": sqlcols("t-", STAGE_COLS), "order": ["t-" + c[0] for c in STAGE_COLS],
          "style": dict(CARD)}
grid = {"id": "grid", "kind": "table", "name": "Formation Tops Grid", "visibleAsSource": True,
        "source": {"connectionId": CONN, "kind": "sql", "statement": GRID_SQL},
        "columns": sqlcols("g-", GRID_COLS), "order": ["g-" + c[0] for c in GRID_COLS],
        "style": dict(CARD)}

# ---------------------------------------------------------------- plugin element
PLUGIN_CFG = {
    "version": 1,
    "map": {"well": "s-well", "x": "s-e", "y": "s-n", "z": "s-tvd", "md": "s-md",
            "color": "s-dls", "stageSize": "s-prop", "stageLabel": "s-stage",
            "tooltip": ["s-rop", "s-inc", "s-form", "s-pad"]},
    "surf": {"layer": "g-form", "x": "g-e", "y": "g-n", "z": "g-tvd", "value": "g-build"},
    "view": {"zExag": 1, "trueScale": False, "scale": "auto", "lineWidth": 5, "markerScale": 1,
             "showStages": True, "showSurface": True, "showLabels": True, "showFootprint": False,
             "projection": "perspective", "layer": "WCA", "camera": None, "camAR": ""},
}
viz = {"id": "viz", "kind": "plugin", "pluginId": PLUGIN, "config": {
    "source": {"kind": "element", "elementId": "surveys"},
    "surfaceSource": {"kind": "element", "elementId": "grid"},
    # A spec-authored multi-column binding did NOT make Sigma deliver rows (metadata arrived,
    # data did not). The plugin registers the columns it needs at runtime via
    # config.setKey("columns", [...]), which is the verified path — so leave these out.
    # Set DECLARE_COLS=1 to put them back for comparison.
    **({"columns": ["s-well", "s-e", "s-n", "s-tvd", "s-md", "s-dls", "s-prop",
                    "s-stage", "s-rop", "s-inc", "s-form", "s-pad"],
        "surfaceColumns": ["g-form", "g-e", "g-n", "g-tvd", "g-build"]}
       if os.environ.get("DECLARE_COLS") == "1" else {}),
    "wellVar": "SelWell",
    "layerVar": "SelLayer",
    "config": json.dumps(PLUGIN_CFG),
    "editMode": False,
    "demo": os.environ.get("PLUGIN_DEMO") == "1",
}}

# ---------------------------------------------------------------- controls / text
hdr_c = {"id": "c-hdr", "kind": "container", "style": {
    "backgroundColor": "#EEF3F8", "borderColor": LINE, "borderWidth": 1, "borderRadius": "round"}}
hdr = {"id": "hdr", "kind": "text", "verticalAlign": "middle", "style": {"color": INK},
       "body": "## 3D Well &amp; Completion Viewer — plugin test"}
sub = {"id": "sub", "kind": "text", "verticalAlign": "middle", "style": {"color": SLATE},
       "body": ("10 horizontal wells on 3 pads, ~50 frac stages each, 3 formation tops — all generated in SQL. "
                "Orbit / zoom the scene, switch formation layer, exaggerate depth, then click a trajectory: "
                "the well name lands in the **Selected well** control and filters the stage table below.")}

def ctrl_list(cid, elid, name, src_el, col):
    return {"kind": "control", "controlId": cid, "id": elid, "name": name,
            "controlType": "list", "selectionMode": "multiple", "mode": "include", "values": [],
            "filters": [{"source": {"kind": "table", "elementId": src_el}, "columnId": col}],
            "source": {"kind": "source", "source": {"kind": "table", "elementId": src_el},
                       "columnId": col}}

ctrl_pad = ctrl_list("PadF", "ctrl-pad", "Pad", "surveys", "s-pad")
ctrl_form = ctrl_list("FormF", "ctrl-form", "Target formation", "surveys", "s-form")
TEXT_CTRL = {"controlType": "text", "case": "insensitive", "mode": "equals",
             "includeNulls": "when-no-value-is-selected", "showOperators": False}
ctrl_well = {"kind": "control", "controlId": "SelWell", "id": "ctrl-well",
             "name": "Selected well (set by the plugin)", **TEXT_CTRL,
             "filters": [{"source": {"kind": "table", "elementId": "stages"}, "columnId": "t-well"}]}
ctrl_layer = {"kind": "control", "controlId": "SelLayer", "id": "ctrl-layer",
              "name": "Formation layer shown", **TEXT_CTRL}

PAGE_ELEMENTS = [hdr_c, hdr, sub, ctrl_pad, ctrl_form, ctrl_well, ctrl_layer,
                 viz, stages, surveys, grid]

LAYOUT = """<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" gridTemplateRows="auto" id="pg">
  <Container elementId="c-hdr" type="grid" gridColumn="1 / 25" gridRow="1 / 7" gridTemplateColumns="repeat(24, 1fr)" gridTemplateRows="auto">
    <Element elementId="hdr" gridColumn="2 / 24" gridRow="1 / 4"/>
    <Element elementId="sub" gridColumn="2 / 24" gridRow="4 / 7"/>
  </Container>
  <Element elementId="ctrl-pad" gridColumn="1 / 7" gridRow="7 / 10"/>
  <Element elementId="ctrl-form" gridColumn="7 / 13" gridRow="7 / 10"/>
  <Element elementId="ctrl-well" gridColumn="13 / 19" gridRow="7 / 10"/>
  <Element elementId="ctrl-layer" gridColumn="19 / 25" gridRow="7 / 10"/>
  <Element elementId="viz" gridColumn="1 / 25" gridRow="10 / 38"/>
  <Element elementId="stages" gridColumn="1 / 25" gridRow="38 / 52"/>
  <Element elementId="surveys" gridColumn="1 / 13" gridRow="52 / 66"/>
  <Element elementId="grid" gridColumn="13 / 25" gridRow="52 / 66"/>
</Page>"""

THEME = {"colors": {"text": INK, "highlight": "#2A78D6", "success": "#1BAF7A",
                    "warning": "#EDA100", "danger": "#E34948", "darkMode": "hidden"},
         "colorOverrides": {"backgroundCanvas": "#FFFFFF", "canvasBackground": "#F4F7FA"},
         "categoricalScheme": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100",
                               "#E87BA4", "#008300", "#4A3AA7", "#E34948"],
         "fonts": {"textFont": "Inter", "dataFont": "Inter"},
         "pageWidth": "full",
         "tableStyles": {"preset": "presentation", "cellSpacing": "small"}}


def build(variant):
    """variant 0 = everything; 1 = drop the text-control filter; 2 = also drop the theme."""
    els = [json.loads(json.dumps(e)) for e in PAGE_ELEMENTS]
    if variant >= 1:
        for e in els:
            if e.get("controlId") == "SelWell":
                e.pop("filters", None)
    doc = {"schemaVersion": 1, "kind": "workbook", "elements": els,
           "pages": [{"id": "pg", "name": "3D Viewer"}],
           "layout": '<?xml version="1.0" encoding="utf-8"?>\n' + LAYOUT}
    if variant < 2:
        doc["settings"] = {"theme": {"overrides": THEME}}
    spec = {"name": "3D Well & Completion Viewer — Plugin Test", "document": doc}
    if FOLDER:
        spec["folderId"] = FOLDER
    return spec


def call(method, path, body=None):
    r = urllib.request.Request(BASE + path, method=method, headers=H,
                               data=json.dumps(body).encode() if body is not None else None)
    return urllib.request.urlopen(r, timeout=180).read().decode()


for variant in (0, 1, 2):
    spec = build(variant)
    try:
        if UPDATE:
            resp = call("PUT", f"/v2/workbooks/{UPDATE}/spec", spec)
        else:
            resp = call("POST", "/v2/workbooks/spec", spec)
        wid = json.loads(resp).get("workbookId") if resp.strip().startswith("{") else None
        if not wid:
            for line in resp.splitlines():
                if "workbookId" in line:
                    wid = line.split()[-1].strip('",')
        wid = wid or UPDATE
        print(f"variant {variant}: ACCEPTED  workbookId={wid}")
        if wid:
            meta = json.loads(call("GET", f"/v2/workbooks/{wid}"))
            print("URL:", meta.get("url"))
        sys.exit(0)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            msg = json.loads(raw).get("message", raw)
        except Exception:
            msg = raw
        print(f"variant {variant}: HTTP {e.code} — {msg[:500]}")
print("ALL VARIANTS FAILED")
sys.exit(1)
