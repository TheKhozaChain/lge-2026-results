#!/usr/bin/env python3
"""Pull the latest IEC 2026 municipal results and rebuild lge-results-explorer.html.

Usage:  python3 refresh.py [output.html]
Reads template.html next to this script and writes lge-results-explorer.html
(or the given file) plus data-version.json beside it.
Per-council files are large (~1 MB each, ~210 of them), so a run takes 1-3 minutes.
"""
import html
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

BASE = "https://results.elections.org.za/dashboards/lge/MapsJason"
EEID = 1887
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template.html")
# Optional first argument: output file (the GitHub Action passes site/index.html)
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "lge-results-explorer.html")


def get(path, tries=3):
    url = f"{BASE}/{path}?rnd={time.time()}"
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": "lge-results-explorer"}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except Exception as e:
            if i == tries - 1:
                raise RuntimeError(f"{path}: {e}")
            time.sleep(2 * (i + 1))


def build(nat, hist, plist, munic):
    plist = {p["ID"]: p for p in plist}
    P = {}

    def pid(r):
        i = r["ID"]
        if i not in P:
            p = plist.get(i) or plist.get(-i) or {}
            P[i] = [p.get("Name") or r["Name"][:10], r["Name"].title(), p.get("sWebColour") or "#888"]
        return i

    def turnout(r0):
        return dict(reg=r0["RegisteredVoters"], cast=r0["TotalVotesCast"], valid=r0["ValidVotesCast"], spoilt=r0["SpoiltVotes"])

    def prog(o):
        return dict(vd=[o["VDsComplete"], o["VDExpected"]], wd=[o["WardsComplete"], o["WardExpected"]],
                    st=[o.get("SeatsComplete", 0), o.get("SeatsExpected", 0)], mc=[o["MuncipalitiesComplete"], o["MunicExpected"]])

    def parties(lst, cap=None):
        lst = sorted(lst, key=lambda r: -r["TotalValidVotes"])
        return [[pid(r), r["TotalValidVotes"], r["PercOfVotes"], r["TotalSeatsWon"], r["WardSeatsWon"], r["CouncilsWon"], r["MajorityWon"]]
                for r in lst if r["TotalValidVotes"] > 0 or r["TotalSeatsWon"] > 0][:cap]

    def h(rows, key=None, val=None):
        out = {}
        for r in rows:
            if key and r[key] != val:
                continue
            if r["lYear"] in (2016, 2021) and r["sPartyAbbr"]:
                out.setdefault(r["sPartyAbbr"], {})[r["lYear"]] = r["iPercentageSupport"]
        return out

    N = dict(rd=nat["ReportDate"][:16], p=parties(nat["PartyBallotResults"]), t=turnout(nat["PartyBallotResults"][0]), g=prog(nat),
             hung=nat["HungCouncils"], maj=nat["MajorityCouncils"], drawn=nat["DeadLockDrawnCouncils"], h=h(hist["National"]), prov=[])
    for pr in nat["ProvinceResults"]:
        pv = dict(id=pr["ProvinceID"], n=pr["Province"], p=parties(pr["PartyBallotResults"]), g=prog(pr),
                  hung=pr["HungCouncils"], maj=pr["MajorityCouncils"], h=h(hist["Provinces"], "lProvinceId", pr["ProvinceID"]), m=[])
        if pr["PartyBallotResults"]:
            pv["t"] = turnout(pr["PartyBallotResults"][0])
        for lm in pr["MunicipalityResults"]:
            md = munic.get(lm["MunicipalityID"]) or lm  # fall back to the summary if a council file failed
            pb = md["PartyBallotResults"]
            mm = dict(id=lm["MunicipalityID"], n=lm["Municipality"], p=parties(pb, 14), g=prog(md), seats=md["SeatsExpected"],
                      hung=lm["HungCouncils"], maj=lm["MajorityCouncils"], drawn=lm["DeadLockDrawnCouncils"],
                      h=h(hist["Municipalities"], "lMunicipalityId", lm["MunicipalityID"]))
            if pb:
                mm["t"] = turnout(pb[0])
            pv["m"].append(mm)
        N["prov"].append(pv)
    N["P"] = P
    return N


SITE_URL = os.environ.get("SITE_URL", "https://thekhozachain.github.io/lge-2026-results/")
JHB = 3003
BRAND = {"ANC": "#1f8a3b", "DA": "#1d5fb4", "EFF": "#c81d25", "MKP": "#8a3fa6", "IFP": "#c99206", "VF PLUS": "#ea7317",
         "PA": "#0a87a8", "ACTIONSA": "#2a9d7f", "SACP": "#8f1d14", "ATM": "#617d2a", "UDM": "#d4a72c", "ACDP": "#3c4fa8",
         "GOOD": "#e05a8a", "RISE": "#e0557a", "BOSA": "#2d6fd1"}


def _top(built, n):
    return [p for p in built["p"] if built["P"][p[0]][0] not in ("OTHER", "IND")][:n]


def _counted(g):
    return round(g["vd"][0] * 100 / g["vd"][1], 1) if g["vd"][1] else 0


def card_text(built):
    """Title and one-line description for the link preview card."""
    P = built["P"]
    counted = _counted(built["g"])
    parties = ", ".join(f"{P[p[0]][0]} {p[2]}%" for p in _top(built, 3))
    desc = f"{counted}% of voting stations counted. Nationally: {parties}."
    jhb = next((m for pv in built["prov"] for m in pv["m"] if m["id"] == JHB), None)
    if jhb and jhb["p"] and jhb["g"]["vd"][0]:
        desc += f" Johannesburg: {P[jhb['p'][0][0]][0]} ahead on {jhb['p'][0][2]}%."
    desc += " Unofficial, built on IEC results and updated every 10 minutes."
    return "SA local elections 2026: the live count, explained", desc


def make_card_image(built, path):
    """1200x630 preview image: count progress and the leading parties nationally."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed; skipping the preview image (pip install pillow).")
        return

    def font(size, bold=True):
        for f in (["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else
                  ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf"]):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                pass
        return ImageFont.load_default(size)

    W, H, X0, X1 = 1200, 630, 72, 1128
    bg, ink, muted, track, accent = "#0f141a", "#e7ecef", "#9ba6b2", "#212a35", "#4cb8ae"
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    P, counted = built["P"], _counted(built["g"])

    d.text((X0, 52), "SOUTH AFRICA  ·  LOCAL ELECTIONS 2026", font=font(24), fill=muted)
    d.text((X0, 88), f"Live count: {counted}% of stations counted", font=font(50), fill=ink)
    d.rounded_rectangle((X0, 168, X1, 184), 8, fill=track)
    d.rounded_rectangle((X0, 168, X0 + max(16, (X1 - X0) * counted / 100), 184), 8, fill=accent)

    rows = _top(built, 5)
    h21 = built["h"]
    top = max([p[2] for p in rows] + [h21.get(P[p[0]][0], {}).get(2021, 0) for p in rows] + [1])
    bx0, bx1, y = 230, 960, 222
    for p in rows:
        a = P[p[0]][0]
        col = BRAND.get(a, "#7a8592")
        d.text((X0, y + 6), a if len(a) <= 8 else a[:7] + "…", font=font(30), fill=ink)
        d.rounded_rectangle((bx0, y + 6, bx1, y + 44), 6, fill=track)
        d.rounded_rectangle((bx0, y + 6, bx0 + max(12, (bx1 - bx0) * p[2] / top), y + 44), 6, fill=col)
        old = h21.get(a, {}).get(2021)
        if old is not None:  # 2021 marker, same as on the page
            x = bx0 + (bx1 - bx0) * old / top
            d.rectangle((x - 2, y, x + 1, y + 50), fill=ink)
        d.text((X1, y + 2), f"{p[2]}%", font=font(30), fill=ink, anchor="ra")
        if old is not None:
            dd = round(p[2] - old, 1)
            d.text((X1, y + 38), f"{'+' if dd >= 0 else '−'}{abs(dd)} pts vs 2021", font=font(17, False),
                   fill="#5cc28a" if dd >= 0 else "#ff7b6b", anchor="ra")
        y += 66

    t = built["rd"]
    when = f"{int(t[8:10])} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(t[5:7]) - 1]} {t[11:16]} SAST"
    d.text((X0, 572), f"Unofficial · IEC results as at {when} · white line = 2021 result", font=font(20, False), fill=muted)
    d.text((X1, 572), SITE_URL.replace("https://", "").rstrip("/"), font=font(20), fill=accent, anchor="ra")
    im.save(path, optimize=True)


def main():
    t0 = time.time()
    print("Fetching national results…")
    nat = get(f"2026/EEID{EEID}LiteMapsNational.js")
    hist = get("HistoryYears/HistoryYearsNational.js")
    plist = get("2016/PartyList.js")
    ids = [m["MunicipalityID"] for p in nat["ProvinceResults"] for m in p["MunicipalityResults"]]
    print(f"Fetching {len(ids)} councils…")

    def one(i):
        try:
            d = get(f"2026/EEID{EEID}Munic{i}.js")
            d["WardResults"] = []  # not used, drop to save memory
            return i, d
        except RuntimeError as e:
            print("  skipped", e, file=sys.stderr)
            return i, None

    with ThreadPoolExecutor(6) as ex:
        munic = {i: d for i, d in ex.map(one, ids) if d}

    if len(munic) < len(ids) * 0.9:
        sys.exit(f"Only {len(munic)}/{len(ids)} councils downloaded; keeping the previous page.")
    built = build(nat, hist, plist, munic)
    data = json.dumps(built, separators=(",", ":")).replace("</", "<\\/")
    title, desc = card_text(built)
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    for k, v in {"__OG_TITLE__": title, "__OG_DESC__": desc, "__SITE_URL__": SITE_URL,
                 "__OG_VER__": built["rd"].replace(":", "").replace("-", "")}.items():
        page = page.replace(k, html.escape(v, quote=True))
    page = page.replace("__DATA__", data)
    make_card_image(built, os.path.join(os.path.dirname(OUT), "og.png"))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    # Small file the hosted page polls to know when to reload
    with open(os.path.join(os.path.dirname(OUT), "data-version.json"), "w") as f:
        json.dump({"rd": built["rd"]}, f)
    g = nat
    print(f"Done in {time.time() - t0:.0f}s. IEC report time {nat['ReportDate'][:16]}, "
          f"{g['Perc_VDsComplete']}% of stations counted, {len(munic)}/{len(ids)} councils loaded.")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
