"""
Example configuration file for USDA data processing.

Copy this file to data_consts.py and fill in your actual values.
DO NOT commit data_consts.py to version control if it contains secrets.
"""
import os

class Constants:
    """Constants used throughout the USDA data processing pipeline."""
    
    PROD_CODE = ["0813600", "0813100", "0813101", "0813500", "4239100",
                 "4232000", "4232001", "4236000", "2226000", "2222000",
                 "2222001", "2224000", "4243000", '4244000']

    # Option 1: Read from environment variable (RECOMMENDED)
    # Set this in your system or .env file: export USDA_API_KEY="your-key-here"
    API_KEY = os.getenv("USDA_API_KEY", "YOUR_API_KEY_HERE")
    
    # Option 2: If you prefer to keep it in the file (NOT RECOMMENDED for production)
    # API_KEY = "your-actual-api-key-here"

    REQ_COLS = ['CommodityDescription', 'CountryName', 'MarketYear', 'CalendarYear', 'Month',
                'AttributeDescription', 'UnitDescription', 'Value']

    COMM_DESC = ["Meal, Rapeseed", "Meal, Soybean", "Meal, Soybean (Local)", "Meal, Sunflowerseed",
                 "Oil, Palm", "Oil, Palm Kernel", "Oil, Rapeseed", "Oil, Soybean",
                 "Oil, Soybean (Local)", "Oil, Sunflowerseed", "Oilseed, Rapeseed",
                 "Oilseed, Soybean", "Oilseed, Soybean (Local)", "Oilseed, Sunflowerseed"]

    AGG_LIST = ['CommodityDescription', 'CountryName', 'MarketYear', 'Month', 'UnitDescription',
                'AttributeDescription']
