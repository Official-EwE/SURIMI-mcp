"""Load CSV exports into PostgreSQL with inferred column types.

Columns are typed by scanning their values (BIGINT / DOUBLE PRECISION / TEXT)
instead of forcing everything to TEXT. TEXT-typed numeric columns were the
root cause of SQL failures in the chat UI: `SUM(employment_fte)` errored with
"function sum(text) does not exist" and `WHERE year IN (2017, 2020)` errored
with "operator does not exist: text = integer", so the model had to CAST on
every query and frequently gave up. Inference is conservative: leading-zero
codes (e.g. "007") and non-fractional code-like columns stay TEXT.
"""
import csv
import os

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


# Non-finite float sentinels. Treated as missing (NULL) rather than letting
# them coerce a column to float or get stored as Postgres NaN/Inf (which break
# IS NULL and silently poison SUM/AVG just like the original TEXT bug did).
_NONFINITE = {
    "nan", "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity",
}

_BIGINT_MIN = -(2 ** 63)
_BIGINT_MAX = 2 ** 63 - 1


class _ColTypeInference:
    """Streaming type inference for one column.

    A column is BIGINT only if every non-empty value is an integer that
    round-trips exactly (so "007" or "+5" are rejected -> they are codes, not
    numbers). It is DOUBLE PRECISION only if every value parses as float AND at
    least one value is genuinely fractional (has '.', 'e', or 'E'); this stops
    integer-looking code columns from being coerced to floats. Otherwise TEXT.
    """

    def __init__(self) -> None:
        self.saw_value = False
        self.could_int = True
        self.could_float = True
        self.saw_fractional = False

    def update(self, v: str | None) -> None:
        if v is None or v == "":
            return
        s = v.strip()
        if s.lower() in _NONFINITE:
            # Missing-value sentinel; don't let it dictate the column type.
            return
        self.saw_value = True
        if self.could_int:
            try:
                iv = int(s)
                if str(iv) != s or not (_BIGINT_MIN <= iv <= _BIGINT_MAX):
                    self.could_int = False
            except ValueError:
                self.could_int = False
        if self.could_float:
            try:
                float(s)
                if any(c in s for c in ".eE"):
                    self.saw_fractional = True
            except ValueError:
                self.could_float = False

    def resolve(self) -> str:
        if not self.saw_value:
            return "TEXT"
        if self.could_int:
            return "BIGINT"
        if self.could_float and self.saw_fractional:
            return "DOUBLE PRECISION"
        return "TEXT"


def infer_pg_type(values) -> str:
    """Infer the PostgreSQL column type for an iterable of raw string values."""
    state = _ColTypeInference()
    for v in values:
        state.update(v)
    return state.resolve()


def _convert(value: str | None, pg_type: str):
    """Convert a raw CSV string to the Python type matching the column."""
    if value is None or value == "":
        return None
    s = value.strip()
    if pg_type in ("BIGINT", "DOUBLE PRECISION"):
        if s.lower() in _NONFINITE:
            return None
        return int(s) if pg_type == "BIGINT" else float(s)
    return value


def _infer_table_types(path: str) -> tuple[list[str], list[str]]:
    """First pass: read headers and infer a PG type per column (O(1) memory)."""
    with open(path, "r") as f:
        reader = csv.reader(f)
        headers = next(reader)
        states = [_ColTypeInference() for _ in headers]
        for row in reader:
            for i in range(len(headers)):
                if i < len(row):
                    states[i].update(row[i])
    return headers, [s.resolve() for s in states]


def main():
    import psycopg2

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

        headers, types = _infer_table_types(path)
        ncol = len(headers)

        cur.execute(f"DROP TABLE IF EXISTS {table}")
        col_defs = ", ".join(f'"{h}" {t}' for h, t in zip(headers, types))
        cur.execute(f"CREATE TABLE {table} ({col_defs})")

        cols = ", ".join(f'"{h}"' for h in headers)
        placeholders = ", ".join(["%s"] * ncol)
        insert_sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"

        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            batch = []
            count = 0
            for row in reader:
                cleaned = [
                    _convert(row[i] if i < len(row) else None, types[i])
                    for i in range(ncol)
                ]
                batch.append(cleaned)
                if len(batch) >= 10000:
                    cur.executemany(insert_sql, batch)
                    count += len(batch)
                    batch = []
            if batch:
                cur.executemany(insert_sql, batch)
                count += len(batch)

        typed = sum(1 for t in types if t != "TEXT")
        print(f"{table}: {count} rows loaded ({ncol} cols, {typed} typed numeric)")

    cur.close()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
