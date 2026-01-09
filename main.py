import os
import pandas as pd
import requests
from typing import List, Any
from data_consts import Constants
import warnings
import streamlit as st

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
    def fetch_commodity_codes():
        url = "https://api.fas.usda.gov/api/psd/commodities"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            print(f"Failed to fetch data for commodity codes")
            return None

    @staticmethod
    def fetch_country_codes():
        url="https://api.fas.usda.gov/api/psd/countries"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            print(f"Failed to fetch data for country codes")
            return None

    @staticmethod
    def fetch_commodity_attributes():
        url = "https://api.fas.usda.gov/api/psd/commodityAttributes"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            print(f"Failed to fetch data for commodity attributes")
            return None

    @staticmethod
    def fetch_units_of_measure():
        url = "https://api.fas.usda.gov/api/psd/unitsOfMeasure"
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            print(f"Failed to fetch data for units of measure")
            return None

    def fetch_USDA_data(self, commodity_code: int, market_year: int) -> Any | None:
        """
        Retrieves USDA PSD Data
        :param commodity_code: Integer, code for a specific commodity
        :param market_year: Integer, Marketing Year
        :return: Res
        """
        print("Fetching USDA Data...")
        url = f'https://api.fas.usda.gov/api/psd/commodity/{commodity_code}/country/all/year/{market_year}'
        headers = {"Accept": "application/json", "X-Api-Key": Constants.API_KEY}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch data for commodity code {commodity_code} and market year {market_year}")
            return None

    def clean_usda_data(self, raw_data: pd.DataFrame, country_codes:pd.DataFrame, commodity_codes:pd.DataFrame, commodity_attributes:pd.DataFrame, units_of_measure: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans the data retrieved from USDA servers
        :param raw_data: pd.DataFrame, raw USDA data
        :param min_market_year: int, minimum market year
        :return: pd.Dataframe, Cleaned data
        """
        print("Cleaning USDA data...")

        # Merge in Commodity Description and Country Name
        raw_data = raw_data.merge(country_codes[["countryCode","countryName"]], on="countryCode", how="left")
        raw_data = raw_data.merge(commodity_codes.rename(columns={"commodityName": "CommodityDescription"}), on="commodityCode", how="left")
        raw_data = raw_data.merge(commodity_attributes.rename(columns={"attributeName":"AttributeDescription"}), on="attributeId", how="left")
        raw_data = raw_data.merge(units_of_measure.rename(columns={"unitDescription": "UnitDescription"}), on="unitId", how="left")

        # Rename Columns
        raw_data.rename(columns={"commodityCode": "CommodityCode", "countryName": "CountryName",
                                 "marketYear":"MarketYear", "calendarYear":"CalendarYear",
                                 "month":"Month", "value":"Value"}, inplace=True)

        # Keep only necessary columns
        clean_data = raw_data[self.required_cols]

        # Assign types to columns
        convert_dict = {'CommodityDescription': str, 'CountryName': str, 'MarketYear': int, 'CalendarYear': int,
                        'Month': int, 'AttributeDescription': str, 'UnitDescription': str, 'Value': float}
        clean_data = clean_data.astype(convert_dict)
        # Strip columns that contain strings
        clean_data = clean_data.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
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

    def get_combined_data(self):
        """
        Combines each USDA data request together
        :return: pd.Dataframe
        """
        combined_data = []
        # For each product code and each year, make a request, then combine it together
        for product_code in self.product_codes:
            for year in self.market_years:
                data = self.fetch_USDA_data(product_code, year)
                if data:
                    combined_data.extend(data)
        print("Data Fetched Successfully")
        return pd.DataFrame(combined_data)



def main():

    """
    Runs the main script.

    :return:
    """

    data_handler = USDADataHandler()
    combined_data = data_handler.get_combined_data()
    comm_codes_df = data_handler.fetch_commodity_codes()
    country_codes_df = data_handler.fetch_country_codes()
    commodity_attributes_df = data_handler.fetch_commodity_attributes()
    units_of_measure_df = data_handler.fetch_units_of_measure()

    clean_data = data_handler.clean_usda_data(raw_data=combined_data,
                                              country_codes=country_codes_df,
                                              commodity_codes=comm_codes_df,
                                              commodity_attributes=commodity_attributes_df,
                                              units_of_measure=units_of_measure_df)

    return clean_data



if __name__ == "__main__":
   df =  main()
   df.to_parquet("data/latest.parquet", index=False, engine="pyarrow")
