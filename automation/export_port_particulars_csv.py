"""Write Supabase port_particulars back to the local CSV that Power BI reads (same columns and order as your file).

    set SUPABASE_SERVICE_ROLE_KEY=<service_role key>        (the public anon key also works: the table is public-read)
    python export_port_particulars_csv.py "..\\..\\Bulk Cargo\\Port Particulars\\port_particulars.csv"

Use it after the GitHub refresh has replaced the rows with the old bad LOA values, instead of refetching them locally.
The current CSV is kept next to it as port_particulars.csv.bak. Refuses to write if bad LOA rows remain (--force overrides).
"""
import argparse
import os
import shutil
import sys

import pandas as pd

from oceanbolt_common import Supabase, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--force", action="store_true", help="write even if rows with loa_* == dwt_* remain")
    a = ap.parse_args()
    rows = Supabase().select_all("port_particulars", ["*"])
    df = pd.DataFrame(rows)
    log("%d rows read from Supabase" % len(df))
    c = df[df["number_of_port_calls"] > 0]
    bad = int(((c["loa_p50"] == c["dwt_p50"]) & (c["loa_p90"] == c["dwt_p90"])).sum())
    if bad and not a.force:
        sys.exit("%d rows with calls still have loa_* == dwt_* in Supabase: let the GitHub refresh finish first "
                 "(or pass --force)." % bad)
    if os.path.exists(a.csv):
        cols = list(pd.read_csv(a.csv, nrows=0).columns)
        df = df[[x for x in cols if x in df.columns] + [x for x in df.columns if x not in cols]]
        shutil.copyfile(a.csv, a.csv + ".bak")
    df = df.sort_values(["platform", "port_id", "window"]).reset_index(drop=True)
    tmp = a.csv + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, a.csv)
    log("wrote %s (%d rows, %d with the old bad LOA values)" % (a.csv, len(df), bad))


if __name__ == "__main__":
    main()
