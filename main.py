import pandas as pd
import requests
from typing import Any, Optional
from data_consts import Constants
import warnings

# Ignore warnings
warnings.filterwarnings('ignore')


class USDADataHandler:
    """
    This class is responsible for extracting data from the USDA, via API.
    The API Key can be found in the constants file.

    """

    def __init__(self):
        self.product_codes = Constants.PROD_CODE
        self.current_year = pd.Timestamp.now().year
        self.market_year = self.current_year + 1
        self.min_market_year = self.market_year - 5
        self.market_years = list(range(self.min_market_year, self.market_year))
        self.required_cols = Constants.REQ_COLS
        self.required_comm_desc = Constants.COMM_DESC
        self.agg_list = Constants.AGG_LIST

    @staticmethod
    def fetch_commodity_codes() -> Optional[pd.DataFrame]:
        """Fetch commodity codes from USDA API."""
        url = "https://api.fas.usda.gov/api/psd/commodities"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return pd.DataFrame(response.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch commodity codes: {e}")
            return None

    @staticmethod
    def fetch_country_codes() -> Optional[pd.DataFrame]:
        """Fetch country codes from USDA API."""
        url = "https://api.fas.usda.gov/api/psd/countries"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return pd.DataFrame(response.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch country codes: {e}")
            return None

    @staticmethod
    def fetch_commodity_attributes() -> Optional[pd.DataFrame]:
        """Fetch commodity attributes from USDA API."""
        url = "https://api.fas.usda.gov/api/psd/commodityAttributes"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return pd.DataFrame(response.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch commodity attributes: {e}")
            return None

    @staticmethod
    def fetch_units_of_measure() -> Optional[pd.DataFrame]:
        """Fetch units of measure from USDA API."""
        url = "https://api.fas.usda.gov/api/psd/unitsOfMeasure"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return pd.DataFrame(response.json())
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch units of measure: {e}")
            return None

    def fetch_USDA_data(self, commodity_code: int, market_year: int) -> Optional[list]:
        """
        Retrieves USDA PSD Data for a specific commodity and market year.
        
        :param commodity_code: Integer, code for a specific commodity
        :param market_year: Integer, Marketing Year
        :return: List of data records or None if request fails
        """
        url = f'https://api.fas.usda.gov/api/psd/commodity/{commodity_code}/country/all/year/{market_year}'
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Failed to fetch data for commodity code {commodity_code} and market year {market_year}: {e}")
            return None

    def clean_usda_data(self, raw_data: pd.DataFrame, country_codes: pd.DataFrame,
                       commodity_codes: pd.DataFrame, commodity_attributes: pd.DataFrame,
                       units_of_measure: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans the data retrieved from USDA servers.
        
        :param raw_data: pd.DataFrame, raw USDA data
        :param country_codes: pd.DataFrame, country code reference data
        :param commodity_codes: pd.DataFrame, commodity code reference data
        :param commodity_attributes: pd.DataFrame, attribute reference data
        :param units_of_measure: pd.DataFrame, unit reference data
        :return: pd.DataFrame, Cleaned data
        """
        print("Cleaning USDA data...")

        if raw_data.empty:
            return pd.DataFrame(columns=self.required_cols)

        # Merge in Commodity Description and Country Name
        raw_data = raw_data.merge(
            country_codes[["countryCode", "countryName"]], on="countryCode", how="left"
        )
        raw_data = raw_data.merge(
            commodity_codes.rename(columns={"commodityName": "CommodityDescription"}),
            on="commodityCode", how="left"
        )
        raw_data = raw_data.merge(
            commodity_attributes.rename(columns={"attributeName": "AttributeDescription"}),
            on="attributeId", how="left"
        )
        raw_data = raw_data.merge(
            units_of_measure.rename(columns={"unitDescription": "UnitDescription"}),
            on="unitId", how="left"
        )

        # Rename Columns
        raw_data.rename(columns={
            "commodityCode": "CommodityCode",
            "countryName": "CountryName",
            "marketYear": "MarketYear",
            "calendarYear": "CalendarYear",
            "month": "Month",
            "value": "Value"
        }, inplace=True)

        # Validate required columns exist
        missing_cols = [col for col in self.required_cols if col not in raw_data.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Keep only necessary columns
        clean_data = raw_data[self.required_cols].copy()

        # Assign types to columns
        convert_dict = {
            'CommodityDescription': str,
            'CountryName': str,
            'MarketYear': int,
            'CalendarYear': int,
            'Month': int,
            'AttributeDescription': str,
            'UnitDescription': str,
            'Value': float
        }
        clean_data = clean_data.astype(convert_dict)

        # Strip string columns (vectorized operation - more efficient than apply)
        string_cols = clean_data.select_dtypes(include=['object']).columns
        for col in string_cols:
            clean_data[col] = clean_data[col].str.strip()

        # Filter commodities
        clean_data = clean_data[clean_data['CommodityDescription'].isin(self.required_comm_desc)]
        # Filter on Marketing Year
        clean_data = clean_data[clean_data["MarketYear"] >= self.min_market_year]
        return clean_data

    def aggregate_usda_data(self, clean_data: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregates the cleaned data
        :param clean_data: pd.DataFrame, cleaned USDA data
        :return: pd.DataFrame, aggregated USDA data
        """
        return clean_data.groupby(self.agg_list)['Value'].sum().reset_index()

    def get_combined_data(self) -> pd.DataFrame:
        """
        Combines each USDA data request together.
        
        :return: pd.DataFrame containing all fetched data
        """
        combined_data = []
        total_requests = len(self.product_codes) * len(self.market_years)
        completed = 0
        
        # For each product code and each year, make a request, then combine it together
        for product_code in self.product_codes:
            for year in self.market_years:
                data = self.fetch_USDA_data(product_code, year)
                if data:
                    combined_data.extend(data)
                completed += 1
                if completed % 10 == 0:
                    print(f"Progress: {completed}/{total_requests} requests completed")
        
        print(f"Data Fetched Successfully: {len(combined_data)} records")
        return pd.DataFrame(combined_data)



def main() -> pd.DataFrame:
    """
    Runs the main script to fetch and process USDA data.
    
    :return: pd.DataFrame containing cleaned USDA data
    :raises: ValueError if required reference data cannot be fetched or API key is missing
    """
    # Validate API key is set
    if not Constants.API_KEY:
        raise ValueError(
            "USDA_API_KEY environment variable is not set. "
            "Please set it locally or configure it in GitHub Secrets for CI/CD.\n"
            "Local setup: export USDA_API_KEY='your-key-here' (Linux/Mac) or "
            "set USDA_API_KEY=your-key-here (Windows)"
        )
    
    data_handler = USDADataHandler()
    
    # Fetch reference data first
    print("Fetching reference data...")
    comm_codes_df = data_handler.fetch_commodity_codes()
    country_codes_df = data_handler.fetch_country_codes()
    commodity_attributes_df = data_handler.fetch_commodity_attributes()
    units_of_measure_df = data_handler.fetch_units_of_measure()
    
    # Validate reference data
    if any(df is None or df.empty for df in [comm_codes_df, country_codes_df,
                                              commodity_attributes_df, units_of_measure_df]):
        raise ValueError("Failed to fetch required reference data. Please check API connection and key.")
    
    # Fetch main data
    combined_data = data_handler.get_combined_data()
    
    if combined_data.empty:
        raise ValueError("No data was fetched from USDA API.")
    
    # Clean and process data
    clean_data = data_handler.clean_usda_data(
        raw_data=combined_data,
        country_codes=country_codes_df,
        commodity_codes=comm_codes_df,
        commodity_attributes=commodity_attributes_df,
        units_of_measure=units_of_measure_df
    )
    
    return clean_data


if __name__ == "__main__":
    try:
        df = main()
        df.to_parquet("data/latest.parquet", index=False, engine="pyarrow")
        print(f"Data saved successfully: {len(df)} records")
    except Exception as e:
        print(f"Error in main execution: {e}")
        raise
