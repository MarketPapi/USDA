"""
Build dashboard marts (balance sheet, map) from data/latest.parquet.
Rebuilds only when marts are missing or latest.parquet has changed; writes _meta.json.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class MartBuilder:
    """
    Builds dashboard marts from data/latest.parquet.

    Rebuild rules:
      - If required marts are missing -> build
      - If latest.parquet changed since last build -> build
      - Else -> skip

    Marts built:
      - mart_balance_sheet_qty.parquet (1000 MT only, annual; includes synthetic World row)
      - mart_map.parquet (unit-aware; SUM for 1000 MT/HA, MEAN for PERCENT/MT/HA)
    """

    SUM_UNITS = {"1000 MT", "1000 HA"}
    RATE_UNITS = {"PERCENT", "MT/HA"}

    def __init__(
        self,
        latest_path: Path = Path("data/latest.parquet"),
        marts_dir: Path = Path("data/marts"),
        meta_path: Path = Path("data/marts/_meta.json"),
    ):
        self.latest_path = latest_path
        self.marts_dir = marts_dir
        self.meta_path = meta_path

        self.marts_dir.mkdir(parents=True, exist_ok=True)

        self.required_marts = [
            self.marts_dir / "mart_balance_sheet_qty.parquet",
            self.marts_dir / "mart_map.parquet",
        ]

    # -------------------------
    # Meta helpers
    # -------------------------
    def _latest_fingerprint(self) -> Dict[str, object]:
        stat = self.latest_path.stat()
        return {
            "latest_path": str(self.latest_path),
            "latest_size": int(stat.st_size),
            "latest_mtime": float(stat.st_mtime),
        }

    def _load_meta(self) -> Optional[Dict[str, object]]:
        if not self.meta_path.exists():
            return None
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_meta(self, meta: Dict[str, object]) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def marts_missing(self) -> bool:
        return any(not p.exists() for p in self.required_marts)

    def needs_rebuild(self) -> bool:
        if not self.latest_path.exists():
            return False
        if self.marts_missing():
            return True

        old = self._load_meta()
        new = self._latest_fingerprint()
        if old is None:
            return True

        return (old.get("latest_size") != new["latest_size"]) or (old.get("latest_mtime") != new["latest_mtime"])

    # -------------------------
    # Read + normalize base dataset
    # -------------------------
    @staticmethod
    def _safe_strip_strings(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        str_cols = out.select_dtypes(include=["object", "string"]).columns
        for c in str_cols:
            out[c] = out[c].astype("string").str.strip()
            out.loc[out[c].isin(["", "nan", "NaN", "None", "<NA>"]), c] = pd.NA
        return out

    @staticmethod
    def _ensure_types(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        for c in ["marketYear", "calendarYear", "month", "attributeId", "unitId"]:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")

        if "value" in out.columns:
            out["value"] = pd.to_numeric(out["value"], errors="coerce").astype("float64")

        # date/date_str if present or buildable
        if "date" not in out.columns and "marketYear" in out.columns and "month" in out.columns:
            valid = out["marketYear"].notna() & out["month"].notna()
            out.loc[valid, "date"] = pd.to_datetime(
                out.loc[valid, "marketYear"].astype(int).astype(str) + "-" +
                out.loc[valid, "month"].astype(int).astype(str).str.zfill(2) + "-01",
                errors="coerce"
            )

        if "date" in out.columns and "date_str" not in out.columns:
            out["date_str"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%d-%m-%Y")

        return out

    @staticmethod
    def _unit_clean(series: pd.Series) -> pd.Series:
        # normalize things like "(1000 MT)" -> "1000 MT"
        return (
            series.astype("string")
            .str.upper()
            .str.replace(r"[()]", "", regex=True)
            .str.strip()
        )

    def _read_latest(self) -> pd.DataFrame:
        df = pd.read_parquet(self.latest_path)

        required = {"commodityName", "countryName", "attributeName", "unitDescription", "marketYear", "value"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"latest.parquet missing required columns: {sorted(missing)}")

        df = self._safe_strip_strings(df)
        df = self._ensure_types(df)

        # Add unit_clean used by marts
        df["unit_clean"] = self._unit_clean(df["unitDescription"])

        return df

    # -------------------------
    # Unit-aware aggregation
    # -------------------------
    def _aggregate_unit_aware(self, df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
        """
        SUM for additive units (1000 MT, 1000 HA)
        MEAN for rate units (PERCENT, MT/HA)
        """
        d = df.copy()

        add_mask = d["unit_clean"].isin({u.upper() for u in self.SUM_UNITS})
        rate_mask = d["unit_clean"].isin({u.upper() for u in self.RATE_UNITS})

        out_frames = []

        if add_mask.any():
            add = d.loc[add_mask].groupby(group_cols, as_index=False)["value"].sum()
            out_frames.append(add)

        if rate_mask.any():
            rate = d.loc[rate_mask].groupby(group_cols, as_index=False)["value"].mean()
            out_frames.append(rate)

        if not out_frames:
            return pd.DataFrame(columns=group_cols + ["value"])

        return pd.concat(out_frames, ignore_index=True)

    # -------------------------
    # Mart builders
    # -------------------------
    def build_balance_sheet_qty(self, df: pd.DataFrame) -> None:
        """
        Quantity-only (1000 MT) annual mart for balance sheet tables.
        Grain:
          commodityName, countryName, marketYear, attributeName, unit_clean + optional mapping dims

        ✅ Adds a synthetic 'World' country as SUM over all countries by:
           commodity + attribute + year (+ unit)
        """
        d = df.copy()

        # Filter to 1000 MT only
        d = d[d["unit_clean"] == "1000 MT"].copy()

        # Keep useful dims (as available)
        keep = [c for c in [
            "commodityCode", "commodityName",
            "countryCode", "countryName",
            "gencCode", "regionCode",
            "attributeId", "attributeName",
            "unitId", "unitDescription", "unit_clean",
            "marketYear",
            "value",
        ] if c in d.columns]

        d = d[keep].dropna(subset=["commodityName", "countryName", "attributeName", "marketYear", "value"]).copy()

        group_cols = [c for c in [
            "commodityCode", "commodityName",
            "countryCode", "countryName",
            "gencCode", "regionCode",
            "attributeId", "attributeName",
            "unitId", "unitDescription", "unit_clean",
            "marketYear",
        ] if c in d.columns]

        # Base mart (country-level)
        mart = d.groupby(group_cols, as_index=False)["value"].sum()

        # -------------------------
        # Build WORLD rows
        # -------------------------
        # Avoid double counting if upstream already contains World
        if "countryName" in mart.columns:
            mart_no_world = mart[mart["countryName"].astype("string").str.upper() != "WORLD"].copy()
        else:
            mart_no_world = mart.copy()

        # Which columns represent "country identity"?
        country_cols = [c for c in ["countryCode", "countryName", "gencCode", "regionCode"] if c in mart_no_world.columns]

        # Group cols for World = all dims except country identity
        world_group_cols = [c for c in group_cols if c not in country_cols]

        world = mart_no_world.groupby(world_group_cols, as_index=False)["value"].sum()

        # Add back country columns with World labels
        if "countryName" in group_cols:
            world["countryName"] = "World"
        if "countryCode" in group_cols:
            # Keep it consistent with your string-cleaning approach
            world["countryCode"] = "WORLD"
        if "gencCode" in group_cols:
            world["gencCode"] = pd.NA
        if "regionCode" in group_cols:
            world["regionCode"] = pd.NA

        # Ensure column order matches mart
        world = world[mart_no_world.columns]

        # Combine
        mart_out = pd.concat([mart_no_world, world], ignore_index=True)

        out_path = self.marts_dir / "mart_balance_sheet_qty.parquet"
        mart_out.to_parquet(out_path, index=False)

    def build_map_mart(self, df: pd.DataFrame) -> None:
        """
        Unit-aware map mart.
        Grain:
          attributeName, marketYear, countryName, gencCode, unit_clean (and unitDescription)
        Aggregation:
          - SUM for 1000 MT / 1000 HA
          - MEAN for PERCENT / MT/HA
        """
        d = df.copy()

        # map needs gencCode
        if "gencCode" not in d.columns:
            raise ValueError("latest.parquet missing gencCode, cannot build mart_map.parquet")

        # Keep only mappable rows
        d = d[d["gencCode"].notna()].copy()

        keep = [c for c in [
            "commodityCode", "commodityName",
            "attributeId", "attributeName",
            "marketYear",
            "countryCode", "countryName",
            "gencCode", "regionCode",
            "unitId", "unitDescription", "unit_clean",
            "value",
        ] if c in d.columns]

        d = d[keep].dropna(subset=["attributeName", "marketYear", "countryName", "gencCode", "unit_clean", "value"]).copy()

        group_cols = [c for c in [
            "commodityCode", "commodityName",
            "attributeId", "attributeName",
            "marketYear",
            "countryCode", "countryName",
            "gencCode", "regionCode",
            "unitId", "unitDescription", "unit_clean",
        ] if c in d.columns]

        mart = self._aggregate_unit_aware(d, group_cols=group_cols)

        out_path = self.marts_dir / "mart_map.parquet"
        mart.to_parquet(out_path, index=False)

    # -------------------------
    # Public entrypoints
    # -------------------------
    def build_all(self) -> None:
        if not self.latest_path.exists():
            raise FileNotFoundError(f"Missing latest parquet: {self.latest_path}")

        df = self._read_latest()

        # Build marts
        self.build_balance_sheet_qty(df)
        self.build_map_mart(df)

        # Save meta after successful build
        meta = self._latest_fingerprint()
        meta["marts_built"] = [p.name for p in self.required_marts]
        meta["built_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._save_meta(meta)

    def build_if_needed(self) -> bool:
        """
        Returns True if rebuilt, False if skipped.
        """
        if self.needs_rebuild():
            self.build_all()
            return True
        return False
