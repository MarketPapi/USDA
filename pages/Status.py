"""
Data Status — track when parquets were last updated and spot issues.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

st.set_page_config(layout="wide")
st.title("Data Status")
st.caption("Track last updates, pipeline runs, and potential issues.")

DATA_DIR = Path("data")
FILES_TO_TRACK = [
    "latest.parquet",
    "release_index.parquet",
    "marts/mart_balance_sheet_qty.parquet",
    "marts/mart_map.parquet",
    "marts/_meta.json",
    "update_info.json",
]
STALE_DAYS = 7


def _file_info(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "size_bytes": None, "modified_utc": None}
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_utc": mtime,
        "modified_iso": mtime.isoformat().replace("+00:00", "Z"),
    }


def _load_json_safe(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# -------------------------
# File table
# -------------------------
st.subheader("Data files")
rows = []
for rel in FILES_TO_TRACK:
    p = DATA_DIR / rel
    info = _file_info(p)
    if info["exists"]:
        size_str = f"{info['size_bytes']:,} B" if info["size_bytes"] is not None else "—"
        modified_str = info["modified_iso"] if info.get("modified_iso") else "—"
        rows.append({"File": rel, "Size": size_str, "Last modified (UTC)": modified_str, "Status": "Present"})
    else:
        rows.append({"File": rel, "Size": "—", "Last modified (UTC)": "—", "Status": "Missing"})

if rows:
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No tracked files found.")

# -------------------------
# Last pipeline run (update_info.json)
# -------------------------
st.subheader("Last pipeline run")
update_info = _load_json_safe(DATA_DIR / "update_info.json")
if update_info:
    last_updated = update_info.get("last_updated", "—")
    status = update_info.get("status", "unknown")
    rows_in_latest = update_info.get("rows_in_latest")
    pairs_refreshed = update_info.get("pairs_refreshed", 0)
    failed_pairs_count = update_info.get("failed_pairs_count", 0)
    message = update_info.get("message")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Last updated", last_updated[:19].replace("T", " ") if isinstance(last_updated, str) else "—")
    with c2:
        st.metric("Status", status)
    with c3:
        st.metric("Rows in latest", f"{rows_in_latest:,}" if rows_in_latest is not None else "—")
    with c4:
        st.metric("Pairs refreshed", pairs_refreshed)

    if failed_pairs_count and failed_pairs_count > 0:
        st.metric("Failed pairs (kept old data)", failed_pairs_count)

    if message:
        st.warning(message)
else:
    st.info("No update_info.json found. Run main.py (or the CI pipeline) to generate it.")

# -------------------------
# Marts build metadata (_meta.json)
# -------------------------
st.subheader("Marts build metadata")
meta = _load_json_safe(DATA_DIR / "marts" / "_meta.json")
if meta:
    built_at = meta.get("built_at", "—")
    marts_built = meta.get("marts_built", [])
    st.text(f"Last marts built (UTC): {built_at[:19].replace('T', ' ') if isinstance(built_at, str) else built_at}")
    st.text(f"Marts: {', '.join(marts_built) if marts_built else '—'}")
else:
    st.info("No _meta.json in data/marts. Marts have not been built or metadata is missing.")

# -------------------------
# Warnings / issues
# -------------------------
st.subheader("Checks")
issues = []

# Missing files
for rel in ["latest.parquet", "release_index.parquet"]:
    if not (DATA_DIR / rel).exists():
        issues.append(f"Missing required file: data/{rel}")

# Status not ok
if update_info and update_info.get("status") not in ("ok", "no_refresh"):
    issues.append(f"Last run status: {update_info.get('status')} — check message above.")

# Stale data: use latest.parquet or update_info last_updated
def _days_ago_utc(iso_str: str) -> float | None:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        # Parse Z or +00:00
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None

latest_path = DATA_DIR / "latest.parquet"
if latest_path.exists():
    info = _file_info(latest_path)
    if info.get("modified_utc"):
        days = (datetime.now(timezone.utc) - info["modified_utc"]).total_seconds() / 86400
        if days > STALE_DAYS:
            issues.append(f"data/latest.parquet is {days:.0f} days old (older than {STALE_DAYS} days).")
elif update_info and update_info.get("last_updated"):
    days = _days_ago_utc(update_info["last_updated"])
    if days is not None and days > STALE_DAYS:
        issues.append(f"Last pipeline run was {days:.0f} days ago (older than {STALE_DAYS} days).")

if issues:
    for msg in issues:
        st.warning(msg)
else:
    st.success("No issues detected. Required files present; data is recent.")
