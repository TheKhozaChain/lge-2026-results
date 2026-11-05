#!/usr/bin/env python3
"""Pull the latest IEC 2026 municipal results and rebuild lge-results-explorer.html.

Usage:  python3 refresh.py [output.html]
Reads template.html next to this script and writes lge-results-explorer.html
(or the given file) plus data-version.json beside it.
Per-council files are large (~1 MB each, ~210 of them), so a run takes 1-3 minutes.
"""
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
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read().replace("__DATA__", data)
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
