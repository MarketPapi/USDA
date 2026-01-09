"""
Utility functions for file I/O operations.

Note: These functions are currently unused in the project.
Consider removing this file if not needed, or integrate into the main workflow.
"""
import pandas as pd
import os
from pathlib import Path
from typing import Optional


def read_csv(path: str) -> pd.DataFrame:
    """
    Read a CSV file into a pandas DataFrame.
    
    :param path: Path to the CSV file
    :return: pd.DataFrame containing the CSV data
    :raises: FileNotFoundError if file doesn't exist
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(path, sep=",", header=0)


def save_excel(df: pd.DataFrame, path: str, name: str, sheet_name: str = "Sheet1") -> None:
    """
    Save a DataFrame to an Excel file.
    
    :param df: DataFrame to save
    :param path: Directory path where file will be saved
    :param name: Name of the Excel file (with or without .xlsx extension)
    :param sheet_name: Name of the Excel sheet
    :raises: ValueError if DataFrame is empty
    """
    if df.empty:
        raise ValueError("Cannot save empty DataFrame")
    
    # Ensure directory exists
    Path(path).mkdir(parents=True, exist_ok=True)
    
    # Ensure .xlsx extension
    if not name.endswith('.xlsx'):
        name = f"{name}.xlsx"
    
    full_path = os.path.join(path, name)
    df.to_excel(full_path, header=True, index=False, sheet_name=sheet_name)


def save_csv(df: pd.DataFrame, path: str, name: str) -> None:
    """
    Save a DataFrame to a CSV file.
    
    :param df: DataFrame to save
    :param path: Directory path where file will be saved
    :param name: Name of the CSV file (with or without .csv extension)
    :raises: ValueError if DataFrame is empty
    """
    if df.empty:
        raise ValueError("Cannot save empty DataFrame")
    
    # Ensure directory exists
    Path(path).mkdir(parents=True, exist_ok=True)
    
    # Ensure .csv extension
    if not name.endswith('.csv'):
        name = f"{name}.csv"
    
    full_path = os.path.join(path, name)
    df.to_csv(full_path, index=False)
