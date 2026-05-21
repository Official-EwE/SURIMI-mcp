"""Load CSV exports into PostgreSQL. Auto-creates tables from CSV headers."""
import csv
import os
import sys

import psycopg2

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://surimi:surimi_mcp_2026@localhost:26613/surimi",
)

CSV_TO_TABLE = {
    "hive_oecd_fsedata.csv": "oecd.fsedata",
    "hive_oecd_oecd_fisheries_support_estimates_eu_coastal_states.csv": "oecd.oecd_fisheries_support_estimates_eu_coastal_states",
    "hive_eu_dcf_eu_dcf_fisheries_economic_performance_aegean_sea.csv": "eu_dcf.eu_dcf_fisheries_economic_performance_aegean_sea",
    "hive_eu_dcf_eu_dcf_fisheries_employment_western_mediterranean.csv": "eu_dcf.eu_dcf_fisheries_employment_western_mediterranean",
    "hive_eu_dcf_aer_economic_national_level.csv": "eu_dcf.aer_economic_national_level",
    "hive_eu_dcf_aer_social_data_2017_2020.csv": "eu_dcf.aer_social_data_2017_2020",
    "hive_eu_dcf_aer_capacity.csv": "eu_dcf.aer_capacity",
    "hive_eu_dcf_aer_economic_2013_2023.csv": "eu_dcf.aer_economic_2013_2023",
    "hive_eu_dcf_fdi_capacity_by_country.csv": "eu_dcf.fdi_capacity_by_country",
    "hive_eu_dcf_fuel.csv": "eu_dcf.fuel",
    "hive_eu_dcf_rev_grp.csv": "eu_dcf.rev_grp",
    "hive_surimi_surimi_empirical_biomass_surveys_western_mediterranean.csv": "surimi.surimi_empirical_biomass_surveys_western_mediterranean",
    "hive_surimi_surimi_simulated_sales_output_aegean_sea.csv": "surimi.surimi_simulated_sales_output_aegean_sea",
}


def main():
    export_dir = os.environ.get("CSV_DIR", "data/exports")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for schema in ["oecd", "eu_dcf", "surimi"]:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    for csv_file, table in CSV_TO_TABLE.items():
        path = os.path.join(export_dir, csv_file)
        if not os.path.exists(path):
            print(f"SKIP {csv_file} (not found)")
            continue

        with open(path, "r") as f:
            reader = csv.reader(f)
            headers = next(reader)

            cur.execute(f"DROP TABLE IF EXISTS {table}")
            col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
            cur.execute(f"CREATE TABLE {table} ({col_defs})")

            cols = ", ".join(f'"{h}"' for h in headers)
            placeholders = ", ".join(["%s"] * len(headers))
            insert_sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"

            batch = []
            count = 0
            for row in reader:
                cleaned = [None if v == "" else v for v in row]
                batch.append(cleaned)
                if len(batch) >= 10000:
                    cur.executemany(insert_sql, batch)
                    count += len(batch)
                    batch = []
            if batch:
                cur.executemany(insert_sql, batch)
                count += len(batch)

        print(f"{table}: {count} rows loaded ({len(headers)} cols)")

    cur.close()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
