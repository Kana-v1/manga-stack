import io
import os
import urllib.request
import zipfile
from dataclasses import dataclass

import pandas as pd

# MovieLens 1M: 1,000,209 ratings (1 to 5 stars) of 3,706 films by 6,040 users, from GroupLens.
# The zip is about 6 MB. It is downloaded once, into DATA_DIR.
MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-1m.zip"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


@dataclass
class MovieLens:
    """The three tables of MovieLens 1M, with the column names that rs_datasets uses."""

    ratings: pd.DataFrame  # user_id, item_id, rating, timestamp (seconds since 1970)
    items: pd.DataFrame  # item_id, title, genres ("Action|Comedy")
    users: pd.DataFrame  # user_id, gender, age, occupation, zip_code


def load_movielens() -> MovieLens:
    """MovieLens 1M as three pandas tables. The first call downloads it."""
    # 1. Download the zip, unless it is in DATA_DIR already.
    folder = os.path.join(DATA_DIR, "ml-1m")
    if not os.path.isdir(folder):
        os.makedirs(DATA_DIR, exist_ok=True)
        with urllib.request.urlopen(MOVIELENS_URL) as response:
            zipfile.ZipFile(io.BytesIO(response.read())).extractall(DATA_DIR)

    # 2. Read the three files. Each line is one row, with "::" between the fields:
    #    "1::1193::5::978300760". The files are Latin-1, not UTF-8 (film titles such as
    #    "Amélie"). The "python" engine is necessary because the separator has 2 characters.
    def read(name: str, columns: list[str]) -> pd.DataFrame:
        return pd.read_csv(
            os.path.join(folder, name),
            sep="::",
            engine="python",
            names=columns,
            encoding="latin-1",
        )

    return MovieLens(
        ratings=read("ratings.dat", ["user_id", "item_id", "rating", "timestamp"]),
        items=read("movies.dat", ["item_id", "title", "genres"]),
        users=read("users.dat", ["user_id", "gender", "age", "occupation", "zip_code"]),
    )
