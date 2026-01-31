"""
USDA PSD data pipeline: fetch from FAS API, merge reference data, write latest.parquet
and release_index.parquet; MartBuilder builds dashboard marts from latest.parquet.
Run as script or via GitHub Action; requires USDA_API_KEY in environment.
"""
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import requests

from data_consts import Constants
from mart_builder import MartBuilder

warnings.filterwarnings("ignore")


class USDADataHandler:
    """
    USDA PSD ingestion with incremental updates based on dataReleaseDates snapshots.
    Handles:
      - first run (no historic index) -> full load
      - no updates -> no requery, return existing dataset
      - partial updates -> only refresh changed commodity/year pairs
      - partial failures -> keep old data for failed pairs
    """

    def __init__(self):
        self.product_codes = Constants.PROD_CODE
        self.required_comm_desc = Constants.COMM_DESC

        # Local cache paths
        self.release_index_path = Path("data/release_index.parquet")
        self.latest_data_path = Path("data/latest.parquet")

    # -------------------------
    # Local IO helpers
    # -------------------------
    @staticmethod
    def _load_parquet(path: Path) -> Optional[pd.DataFrame]:
        if path.exists():
            return pd.read_parquet(path)
        return None

    @staticmethod
    def _save_parquet(df: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    def _write_update_info(
        self,
        status: str,
        rows_in_latest: int,
        *,
        pairs_refreshed: int = 0,
        failed_pairs_count: int = 0,
        message: Optional[str] = None,
    ) -> None:
        """Write data/update_info.json for dashboard status page."""
        path = self.release_index_path.parent / "update_info.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "rows_in_latest": rows_in_latest,
            "pairs_refreshed": pairs_refreshed,
            "failed_pairs_count": failed_pairs_count,
            "message": message,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -------------------------
    # Key normalization helpers
    # -------------------------
    @staticmethod
    def _zfill_commodity_code(series: pd.Series, width: int = 7) -> pd.Series:
        """
        Normalize commodityCode to zero-padded string, preserving leading zeros.
        Example: 813600 -> "0813600" if width=7.
        """
        x = pd.to_numeric(series, errors="coerce").astype("Int64")
        x = x.astype("string").str.replace("<NA>", "", regex=False)
        return x.str.zfill(width)

    # -------------------------
    # Reference endpoints
    # -------------------------
    @staticmethod
    def fetch_commodity_codes() -> Optional[pd.DataFrame]:
        url = "https://api.fas.usda.gov/api/psd/commodities"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return pd.DataFrame(r.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch commodity codes: {e}")
            return None

    @staticmethod
    def fetch_country_codes() -> Optional[pd.DataFrame]:
        url = "https://api.fas.usda.gov/api/psd/countries"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return pd.DataFrame(r.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch country codes: {e}")
            return None

    @staticmethod
    def fetch_commodity_attributes() -> Optional[pd.DataFrame]:
        url = "https://api.fas.usda.gov/api/psd/commodityAttributes"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return pd.DataFrame(r.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch commodity attributes: {e}")
            return None

    @staticmethod
    def fetch_units_of_measure() -> Optional[pd.DataFrame]:
        url = "https://api.fas.usda.gov/api/psd/unitsOfMeasure"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return pd.DataFrame(r.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch units of measure: {e}")
            return None

    # -------------------------
    # Release metadata (dataReleaseDates)
    # -------------------------
    @staticmethod
    def fetch_available_years(commodity_code: Union[int, str]) -> Optional[pd.DataFrame]:
        url = f"https://api.fas.usda.gov/api/psd/commodity/{commodity_code}/dataReleaseDates"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            df = pd.DataFrame(r.json())
            return df
        except (requests.RequestException, ValueError) as e:
            print(f"Data Release Dates error for {commodity_code}: {e}")
            return None

    def build_release_index(self) -> pd.DataFrame:
        frames = []
        for code in self.product_codes:
            df = self.fetch_available_years(code)
            if df is None or df.empty:
                continue
            frames.append(df)

        if not frames:
            raise ValueError("No release index data fetched (all empty/failed).")

        release_index = pd.concat(frames, ignore_index=True)

        needed = ["commodityCode", "marketYear", "releaseYear", "releaseMonth"]
        missing = [c for c in needed if c not in release_index.columns]
        if missing:
            raise ValueError(f"Release index missing columns: {missing}")

        # Keep as strings for release snapshot comparison (no zfill needed here)
        release_index["commodityCode"] = release_index["commodityCode"].astype(str)
        release_index["marketYear"] = release_index["marketYear"].astype(int)
        release_index["releaseYear"] = release_index["releaseYear"].astype(int)
        release_index["releaseMonth"] = release_index["releaseMonth"].astype(int)

        return release_index

    @staticmethod
    def _release_rows_set(df: pd.DataFrame) -> set[tuple[str, int, int, int]]:
        cols = ["commodityCode", "marketYear", "releaseYear", "releaseMonth"]
        x = df[cols].copy()
        x["commodityCode"] = x["commodityCode"].astype(str)
        x["marketYear"] = x["marketYear"].astype(int)
        x["releaseYear"] = x["releaseYear"].astype(int)
        x["releaseMonth"] = x["releaseMonth"].astype(int)
        return set(map(tuple, x.to_numpy()))

    @staticmethod
    def _pairs_from_release_delta(delta_rows: set[tuple[str, int, int, int]]) -> list[tuple[str, int]]:
        pairs = {(cc, my) for (cc, my, ry, rm) in delta_rows}
        return sorted(pairs)

    def plan_pairs_to_refresh(
        self,
        new_release_index: pd.DataFrame,
        old_release_index: Optional[pd.DataFrame]
    ) -> list[tuple[str, int]]:
        new_set = self._release_rows_set(new_release_index)
        if old_release_index is None or old_release_index.empty:
            delta_rows = new_set
        else:
            old_set = self._release_rows_set(old_release_index)
            delta_rows = new_set - old_set
        return self._pairs_from_release_delta(delta_rows)

    # -------------------------
    # Main PSD data endpoint
    # -------------------------
    def fetch_USDA_data(self, commodity_code: Union[int, str], market_year: int) -> Optional[list]:
        url = f"https://api.fas.usda.gov/api/psd/commodity/{commodity_code}/country/all/year/{market_year}"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Failed fetch for commodity {commodity_code} year {market_year}: {e}")
            return None

    # -------------------------
    # Merge and clean
    # -------------------------
    def merge_usda_data(
        self,
        raw_data: pd.DataFrame,
        country_codes: pd.DataFrame,
        commodity_codes: pd.DataFrame,
        commodity_attributes: pd.DataFrame,
        units_of_measure: pd.DataFrame,
    ) -> pd.DataFrame:
        raw = raw_data.copy()

        # ---- Normalize RAW keys ----
        if "commodityCode" in raw.columns:
            raw["commodityCode"] = self._zfill_commodity_code(raw["commodityCode"], width=7)

        if "countryCode" in raw.columns:
            raw["countryCode"] = raw["countryCode"].astype("string").str.strip().str.upper()

        for c in ["attributeId", "unitId", "marketYear", "calendarYear", "month"]:
            if c in raw.columns:
                raw[c] = pd.to_numeric(raw[c], errors="coerce").astype("Int64")

        if "value" in raw.columns:
            raw["value"] = pd.to_numeric(raw["value"], errors="coerce").astype("float64")

        # ---- Normalize REFERENCE keys and select minimal columns ----
        cc = country_codes.copy()
        if "countryCode" in cc.columns:
            cc["countryCode"] = cc["countryCode"].astype("string").str.strip().str.upper()
        cc = cc[[c for c in ["countryCode", "countryName", "regionCode", "gencCode"] if c in cc.columns]]

        com = commodity_codes.copy()
        if "commodityCode" in com.columns:
            com["commodityCode"] = self._zfill_commodity_code(com["commodityCode"], width=7)
        com = com[[c for c in ["commodityCode", "commodityName"] if c in com.columns]]

        attr = commodity_attributes.copy()
        if "attributeId" in attr.columns:
            attr["attributeId"] = pd.to_numeric(attr["attributeId"], errors="coerce").astype("Int64")
        attr = attr[[c for c in ["attributeId", "attributeName"] if c in attr.columns]]

        unit = units_of_measure.copy()
        if "unitId" in unit.columns:
            unit["unitId"] = pd.to_numeric(unit["unitId"], errors="coerce").astype("Int64")
        unit = unit[[c for c in ["unitId", "unitDescription"] if c in unit.columns]]

        # ---- Merge ----
        merged = raw.merge(cc, on="countryCode", how="left")
        merged = merged.merge(com, on="commodityCode", how="left")
        merged = merged.merge(attr, on="attributeId", how="left")
        merged = merged.merge(unit, on="unitId", how="left")

        return merged

    def clean_usda_data(self, merged_data: pd.DataFrame) -> pd.DataFrame:
        """
        Keep all columns as-is, assign correct types, strip strings safely,
        filter commodities, and add date/date_str.
        """
        df = merged_data.copy()

        # Strip/normalize all string-like columns safely
        str_cols = df.select_dtypes(include=["object", "string"]).columns
        for c in str_cols:
            df[c] = df[c].astype("string").str.strip()
            df.loc[df[c].isin(["", "nan", "NaN", "None", "<NA>"]), c] = pd.NA

        # Normalize codes (optional but harmless)
        if "countryCode" in df.columns:
            df["countryCode"] = df["countryCode"].str.upper()
        if "gencCode" in df.columns:
            df["gencCode"] = df["gencCode"].str.upper()

        # Enforce numeric columns
        for c in ["marketYear", "calendarYear", "month", "attributeId", "unitId"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")

        # Month sanity
        if "month" in df.columns:
            df = df[df["month"].isna() | df["month"].between(1, 12)].copy()

        # Filter to your commodity list
        if "commodityName" in df.columns and getattr(self, "required_comm_desc", None):
            df = df[df["commodityName"].isin(self.required_comm_desc)].copy()

        # Add date + date_str (dd-mm-yyyy) for dashboards
        if "marketYear" in df.columns and "month" in df.columns:
            valid = df["marketYear"].notna() & df["month"].notna()
            df.loc[valid, "date"] = pd.to_datetime(
                df.loc[valid, "marketYear"].astype(int).astype(str) + "-" +
                df.loc[valid, "month"].astype(int).astype(str).str.zfill(2) + "-01",
                errors="coerce"
            )
            df.loc[valid, "date_str"] = df.loc[valid, "date"].dt.strftime("%d-%m-%Y")

        return df

    # -------------------------
    # Incremental update runner
    # -------------------------
    def run_update(self) -> pd.DataFrame:
        if not Constants.API_KEY:
            raise ValueError("USDA_API_KEY is not set.")

        # 1) New release index
        new_release_index = self.build_release_index()

        # 2) Old release index
        old_release_index = self._load_parquet(self.release_index_path)

        # 3) Pairs to refresh
        pairs_to_refresh = self.plan_pairs_to_refresh(new_release_index, old_release_index)

        # No updates -> return existing
        if old_release_index is not None and len(pairs_to_refresh) == 0:
            print("No new release rows detected. Skipping PSD fetch.")
            self._save_parquet(new_release_index, self.release_index_path)

            existing = self._load_parquet(self.latest_data_path)

            # Ensure marts exist and are up-to-date when no PSD refresh
            if existing is not None and not existing.empty and self.latest_data_path.exists():
                rebuilt = MartBuilder(latest_path=self.latest_data_path).build_if_needed()
                print("Marts rebuilt." if rebuilt else "Marts already up-to-date.")

            rows = len(existing) if existing is not None else 0
            self._write_update_info("no_refresh", rows)
            return existing if existing is not None else pd.DataFrame()

        # 4) Fetch reference tables
        comm_codes_df = self.fetch_commodity_codes()
        country_codes_df = self.fetch_country_codes()
        commodity_attributes_df = self.fetch_commodity_attributes()
        units_of_measure_df = self.fetch_units_of_measure()

        if any(df is None or df.empty for df in [comm_codes_df, country_codes_df, commodity_attributes_df, units_of_measure_df]):
            raise ValueError("Failed to fetch reference data (commodities/countries/attributes/units).")

        # 5) Fetch PSD only for needed pairs
        combined_updates = []
        succeeded_pairs: list[tuple[str, int]] = []
        failed_pairs: list[tuple[str, int]] = []

        print(f"Refreshing {len(pairs_to_refresh)} commodity/year pairs...")

        for cc, my in pairs_to_refresh:
            data = self.fetch_USDA_data(cc, int(my))
            if data:
                combined_updates.extend(data)
                succeeded_pairs.append((str(cc), int(my)))
            else:
                failed_pairs.append((str(cc), int(my)))

        if len(combined_updates) == 0:
            print("All PSD fetches failed or returned empty. Keeping existing dataset.")
            self._save_parquet(new_release_index, self.release_index_path)

            existing = self._load_parquet(self.latest_data_path)

            # Ensure marts exist even when all PSD fetches failed
            if existing is not None and not existing.empty and self.latest_data_path.exists():
                rebuilt = MartBuilder(latest_path=self.latest_data_path).build_if_needed()
                print("Marts rebuilt." if rebuilt else "Marts already up-to-date.")

            rows = len(existing) if existing is not None else 0
            self._write_update_info(
                "refresh_failed", rows,
                pairs_refreshed=len(pairs_to_refresh),
                failed_pairs_count=len(failed_pairs),
                message="All PSD fetches failed or returned empty.",
            )
            return existing if existing is not None else pd.DataFrame()

        updates_raw = pd.DataFrame(combined_updates)

        # 6) Merge + clean updates (merge normalizes keys itself)
        updates_merged = self.merge_usda_data(
            raw_data=updates_raw,
            country_codes=country_codes_df,
            commodity_codes=comm_codes_df,
            commodity_attributes=commodity_attributes_df,
            units_of_measure=units_of_measure_df,
        )
        updates_clean = self.clean_usda_data(updates_merged)

        # 7) Replace refreshed partitions in latest.parquet (FAST)
        existing = self._load_parquet(self.latest_data_path)
        refresh_set = set((str(cc), int(my)) for cc, my in succeeded_pairs)

        # Normalize update keys for replacement
        if "commodityCode" in updates_clean.columns:
            updates_clean["commodityCode"] = self._zfill_commodity_code(updates_clean["commodityCode"], width=7)
        if "marketYear" in updates_clean.columns:
            updates_clean["marketYear"] = pd.to_numeric(updates_clean["marketYear"], errors="coerce").astype("Int64")

        if existing is None or existing.empty:
            final_df = updates_clean
        else:
            # Normalize existing keys
            if "commodityCode" in existing.columns:
                existing["commodityCode"] = self._zfill_commodity_code(existing["commodityCode"], width=7)
            if "marketYear" in existing.columns:
                existing["marketYear"] = pd.to_numeric(existing["marketYear"], errors="coerce").astype("Int64")

            # Detect corrupted existing parquet (names mostly missing) -> rebuild
            looks_bad = False
            for col in ["countryName", "commodityName", "attributeName", "unitDescription"]:
                if col in existing.columns:
                    miss_rate = existing[col].isna().mean()
                    if miss_rate > 0.95:
                        looks_bad = True
                        break

            if looks_bad:
                print("Existing latest.parquet appears corrupted (reference names mostly missing). Rebuilding from scratch.")
                final_df = updates_clean
            else:
                refresh_keys = pd.DataFrame(list(refresh_set), columns=["commodityCode", "marketYear"])
                refresh_keys["commodityCode"] = self._zfill_commodity_code(refresh_keys["commodityCode"], width=7)
                refresh_keys["marketYear"] = pd.to_numeric(refresh_keys["marketYear"], errors="coerce").astype("Int64")

                existing_kept = existing.merge(
                    refresh_keys,
                    on=["commodityCode", "marketYear"],
                    how="left",
                    indicator=True
                )
                existing_kept = existing_kept[existing_kept["_merge"] == "left_only"].drop(columns=["_merge"])
                final_df = pd.concat([existing_kept, updates_clean], ignore_index=True)

            # Dedupe safeguard
            candidate_keys = ["commodityCode", "countryCode", "marketYear", "calendarYear", "month", "attributeId", "unitId"]
            dedupe_cols = [c for c in candidate_keys if c in final_df.columns]
            if dedupe_cols:
                final_df = final_df.drop_duplicates(subset=dedupe_cols, keep="last")

        self._save_parquet(final_df, self.latest_data_path)

        # 8) Save new release index snapshot last
        self._save_parquet(new_release_index, self.release_index_path)

        # Build marts from latest.parquet (skipped if already up-to-date)
        rebuilt = MartBuilder(latest_path=self.latest_data_path).build_if_needed()
        print("Marts rebuilt." if rebuilt else "Marts already up-to-date.")

        self._write_update_info(
            "ok",
            len(final_df),
            pairs_refreshed=len(succeeded_pairs),
            failed_pairs_count=len(failed_pairs),
            message=None if not failed_pairs else f"{len(failed_pairs)} commodity/year pair(s) failed.",
        )

        if failed_pairs:
            print(f"Warning: {len(failed_pairs)} pairs failed and were NOT updated (kept old data for them).")

        print(f"Update complete. Stored rows: {len(final_df)}")
        return final_df


def main() -> pd.DataFrame:
    if not Constants.API_KEY:
        raise ValueError("USDA_API_KEY environment variable is not set.")

    handler = USDADataHandler()
    return handler.run_update()


if __name__ == "__main__":
    try:
        df = main()
        if df is None or df.empty:
            print("No data written (no updates and no existing dataset).")
        else:
            print(f"Done. Rows available: {len(df)}")
    except Exception as e:
        print(f"Error in main execution: {e}")
        raise
