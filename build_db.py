"""Builds bulk_cargo.duckdb from the raw voyage CSV and reference lookup CSVs.

Run once: `python build_db.py`. Re-run any time the source CSVs change.
"""
import os
import duckdb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(BASE_DIR, "_references")
VOYAGES_CSV = os.path.join(BASE_DIR, "bulk_tradeflows_lite.csv")
DB_PATH = os.path.join(BASE_DIR, "bulk_cargo.duckdb")


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    con = duckdb.connect(DB_PATH)

    print("Loading voyages...")
    con.execute(f"""
        CREATE TABLE voyages AS
        SELECT
            voyage_id, flow_id,
            CAST(imo AS BIGINT) AS imo,
            commodity_value,
            CAST(volume AS DOUBLE) AS volume,
            CAST(load_port_id AS INTEGER) AS load_port_id,
            CAST(load_port_arrived_at AS TIMESTAMP) AS load_port_arrived_at,
            CAST(load_port_berthed_at AS TIMESTAMP) AS load_port_berthed_at,
            CAST(load_port_departed_at AS TIMESTAMP) AS load_port_departed_at,
            CAST(load_port_days_total AS DOUBLE) AS load_port_days_total,
            CAST(load_port_days_berthed AS DOUBLE) AS load_port_days_berthed,
            CAST(load_port_days_waiting AS DOUBLE) AS load_port_days_waiting,
            CAST(discharge_port_id AS INTEGER) AS discharge_port_id,
            CAST(discharge_port_arrived_at AS TIMESTAMP) AS discharge_port_arrived_at,
            CAST(discharge_port_berthed_at AS TIMESTAMP) AS discharge_port_berthed_at,
            CAST(discharge_port_departed_at AS TIMESTAMP) AS discharge_port_departed_at,
            CAST(discharge_port_days_total AS DOUBLE) AS discharge_port_days_total,
            CAST(discharge_port_days_berthed AS DOUBLE) AS discharge_port_days_berthed,
            CAST(discharge_port_days_waiting AS DOUBLE) AS discharge_port_days_waiting,
            CAST(days_steaming AS DOUBLE) AS days_steaming,
            CAST(days_total_duration AS DOUBLE) AS days_total_duration,
            CAST(distance_calculated AS DOUBLE) AS distance_calculated,
            CAST(distance_actual AS DOUBLE) AS distance_actual,
            vessel_type
        FROM read_csv_auto('{VOYAGES_CSV}', ALL_VARCHAR=TRUE)
    """)

    print("Loading dim_load_ports...")
    con.execute(f"""
        CREATE TABLE dim_load_ports AS
        SELECT
            CAST(load_port_id AS INTEGER) AS port_id,
            load_port AS port_name,
            CAST(load_port_lat AS DOUBLE) AS lat,
            CAST(load_port_lon AS DOUBLE) AS lon,
            load_clarksons_region AS clarksons_region,
            load_country AS country,
            load_country_short_name AS country_short_name,
            load_continent AS continent,
            "load_region_(un)" AS region_un,
            "load_sub-region_(un)" AS subregion_un
        FROM read_csv_auto('{os.path.join(REF_DIR, "ml_ob_load_ports.csv")}', ALL_VARCHAR=TRUE)
    """)

    print("Loading dim_discharge_ports...")
    con.execute(f"""
        CREATE TABLE dim_discharge_ports AS
        SELECT
            CAST(disch_port_id AS INTEGER) AS port_id,
            disch_port AS port_name,
            CAST(disch_port_lat AS DOUBLE) AS lat,
            CAST(disch_port_lon AS DOUBLE) AS lon,
            disch_clarksons_region AS clarksons_region,
            disch_country AS country,
            disch_country_short_name AS country_short_name,
            disch_continent AS continent,
            "disch_region_(un)" AS region_un,
            "disch_sub-region_(un)" AS subregion_un
        FROM read_csv_auto('{os.path.join(REF_DIR, "ml_ob_discharge_ports.csv")}', ALL_VARCHAR=TRUE)
    """)

    print("Loading dim_vessels...")
    con.execute(f"""
        CREATE TABLE dim_vessels AS
        SELECT DISTINCT
            CAST(imo AS BIGINT) AS imo,
            vessel_name,
            segment AS vessel_segment,
            sub_segment AS vessel_sub_segment,
            CAST(dwt AS DOUBLE) AS dwt
        FROM read_csv_auto('{os.path.join(REF_DIR, "ml_ob_vessels.csv")}', ALL_VARCHAR=TRUE)
        WHERE imo IS NOT NULL
    """)

    print("Loading dim_commodities...")
    con.execute(f"""
        CREATE TABLE dim_commodities AS
        SELECT DISTINCT
            commodity_value,
            commodity,
            commodity_group,
            commodity_type,
            cargo_type
        FROM read_csv_auto('{os.path.join(REF_DIR, "ml_bulk_commodities.csv")}', ALL_VARCHAR=TRUE)
        WHERE commodity_value IS NOT NULL
    """)

    print("Creating voyages_enriched view...")
    con.execute("""
        CREATE VIEW voyages_enriched AS
        SELECT
            v.voyage_id, v.flow_id, v.imo,
            ves.vessel_name, ves.vessel_segment, ves.vessel_sub_segment, ves.dwt,
            v.vessel_type,
            v.commodity_value,
            com.commodity, com.commodity_group, com.commodity_type, com.cargo_type,
            v.volume,
            v.load_port_id, lp.port_name AS load_port, lp.country AS load_country,
            lp.country_short_name AS load_country_short, lp.continent AS load_continent,
            lp.clarksons_region AS load_region, lp.region_un AS load_region_un,
            lp.subregion_un AS load_subregion_un, lp.lat AS load_lat, lp.lon AS load_lon,
            v.load_port_arrived_at, v.load_port_berthed_at, v.load_port_departed_at,
            v.load_port_days_total, v.load_port_days_berthed, v.load_port_days_waiting,
            v.discharge_port_id, dp.port_name AS discharge_port, dp.country AS discharge_country,
            dp.country_short_name AS discharge_country_short, dp.continent AS discharge_continent,
            dp.clarksons_region AS discharge_region, dp.region_un AS discharge_region_un,
            dp.subregion_un AS discharge_subregion_un, dp.lat AS discharge_lat, dp.lon AS discharge_lon,
            v.discharge_port_arrived_at, v.discharge_port_berthed_at, v.discharge_port_departed_at,
            v.discharge_port_days_total, v.discharge_port_days_berthed, v.discharge_port_days_waiting,
            v.days_steaming, v.days_total_duration, v.distance_calculated, v.distance_actual,
            date_trunc('year', v.load_port_arrived_at) AS load_year,
            date_trunc('month', v.load_port_arrived_at) AS load_month
        FROM voyages v
        LEFT JOIN dim_vessels ves ON v.imo = ves.imo
        LEFT JOIN dim_commodities com ON v.commodity_value = com.commodity_value
        LEFT JOIN dim_load_ports lp ON v.load_port_id = lp.port_id
        LEFT JOIN dim_discharge_ports dp ON v.discharge_port_id = dp.port_id
    """)

    for tbl in ["voyages", "dim_load_ports", "dim_discharge_ports", "dim_vessels", "dim_commodities"]:
        n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        print(f"{tbl}: {n:,} rows")
    n = con.execute("SELECT count(*) FROM voyages_enriched").fetchone()[0]
    print(f"voyages_enriched: {n:,} rows")

    con.close()
    print(f"Done. Database at {DB_PATH}")


if __name__ == "__main__":
    main()
