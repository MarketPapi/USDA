"""
Pipeline constants: FAS product codes, commodity descriptions, and USDA_API_KEY from env.
Loads .env via python-dotenv if present (local dev); in CI use GitHub Secrets.
"""
import os
from pathlib import Path

if Path(".env").exists():
    from dotenv import load_dotenv
    load_dotenv()


class Constants:
    """Constants used throughout the USDA data processing pipeline."""

    PROD_CODE = [
        "0813600", "0813100", "0813101", "0813500", "4239100",
        "4232000", "4232001", "4236000", "2226000", "2222000",
        "2222001", "2224000", "4243000", "4244000"
    ]

    _raw_key = os.getenv("USDA_API_KEY")
    API_KEY = _raw_key.strip() if _raw_key else None
    if not API_KEY:
        raise RuntimeError("USDA_API_KEY is not set")

    COMM_DESC = [
        "Meal, Rapeseed", "Meal, Soybean", "Meal, Soybean (Local)",
        "Meal, Sunflowerseed", "Oil, Palm", "Oil, Palm Kernel",
        "Oil, Rapeseed", "Oil, Soybean", "Oil, Soybean (Local)",
        "Oil, Sunflowerseed", "Oilseed, Rapeseed", "Oilseed, Soybean",
        "Oilseed, Soybean (Local)", "Oilseed, Sunflowerseed"
    ]
