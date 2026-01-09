import pandas as pd
import os


# Function to read the file
def read_excel(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=",", header=0)
    return df


# Function to save as excel
def save_excel(df: pd.DataFrame, path: str, name: str, sheet_name: str) -> None:
    full_path = os.path.join(path, name)
    df.to_excel(full_path, header=True, index=False, sheet_name=sheet_name)


# Function to save as csv
def save_csv(df: pd.DataFrame, path: str, name: str) -> None:
    full_path = os.path.join(path, name)
    df.to_csv(full_path)
