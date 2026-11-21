import pandas as pd
import numpy as np
from scipy.sparse import dok_matrix


def baseline(
    train_data: pd.DataFrame,
    test_users: list[int],
) -> pd.DataFrame:
    popular_items = train_data["item_id"].value_counts().index  # most popular first
    seen = train_data.groupby("user_id")["item_id"].apply(set)  # items each user rated in train

    users = []
    items = []
    ratings = []

    for i, user in enumerate(test_users):
        unseen_popular = [item for item in popular_items if item not in seen[user]][:10]
        users.extend([user] * 10)
        items.extend(unseen_popular)
        ratings.extend([1] * 10)

    return pd.DataFrame({"user_id": users, "item_id": items, "rating": ratings})


def ease(
    train_data: pd.DataFrame,
    test_users: list[int],
) -> pd.DataFrame:
    user_num = train_data["user_id"].max() + 1
    item_num = train_data["item_id"].max() + 1

    ratings_matrix = dok_matrix((user_num, item_num), dtype=np.float32)
    for _, user, item, rating in train_data[["user_id", "item_id", "rating"]].itertuples():
        ratings_matrix[user, item] = rating

    def calc_weights_matrix(ratings_matrix: dok_matrix, lambd=1000) -> np.ndarray:
        R = ratings_matrix

        P = np.linalg.inv(R.T @ R + lambd * np.eye(ratings_matrix.get_shape()[1]))
        W = -P / np.diag(P) + np.eye(P.shape[0])

        return W

    weights_matrix = calc_weights_matrix(ratings_matrix)

    assert weights_matrix.shape == (item_num, item_num)

    def calc_top_k_predictions(
        ratings_matrix: dok_matrix,
    ) -> tuple[np.ndarray, np.ndarray]:
        scores = ratings_matrix.dot(weights_matrix)
        user_scores = scores[test_users]  # type: ignore

        seen = ratings_matrix.tocsr()[test_users].toarray() > 0  # items each test user rated in train
        user_scores[seen] = -np.inf  # never recommend them: a user rates a movie only once

        top_k_preds = np.argsort(user_scores, descending=True)[:, :10].tolist()

        top_k_scores = np.sort(user_scores, descending=True)[:, :10]
        top_k_scores = top_k_scores.tolist()

        return (top_k_preds, top_k_scores)

    top_k_predictions, top_k_scores = calc_top_k_predictions(ratings_matrix)

    users = []
    items = []
    ratings = []

    for i, user in enumerate(test_users):
        users.extend([user] * 10)
        items.extend(top_k_predictions[i])
        ratings.extend(top_k_scores[i])

    return pd.DataFrame({"user_id": users, "item_id": items, "rating": ratings})


def user2user_CF(
    train_data: pd.DataFrame,
    test_users: list[int],
) -> pd.DataFrame:
    user_num = len(train_data["user_id"].unique())
    items_num = len(train_data["item_id"].unique())

    R = train_data.pivot(index="user_id", columns="item_id", values="rating").fillna(0)  # ratings

    R_nan = R.replace(0, np.nan)
    R_mean = R_nan.mean(axis=1)  # mean ratings per user excluding items that user didn't rate
    R_norm = R_nan.sub(R_mean, axis=0)

    def calc_similarities() -> np.ndarray:
        """
        u1, u2 - users
        i - item

        Sim(u1, u2) =  nominator / denominator

        nominator = sum(R_norm[u1][i_n] * R_norm[u2][i_n])
        denominator = sqrt( sum(R_norm[u1][i])^2 * sum(R_norm[u2][i])^2 )

        [!] skipping R_norm[i][j] == np.nan
        """
        R_arr = R_norm.to_numpy(dtype=np.float64)

        mask = ~np.isnan(R_arr)  # True where rated
        X = np.nan_to_num(R_arr)  # unrated -> 0

        # ---

        nominator = X @ X.T  # sum over co-rated items (unrated are 0, so they drop out)
        """
                  X (2×3)                 X.T (3×2)
                  A  B  C                 u1  u2
            u1 [  1  2  0 ]          A [   1   3 ]
            u2 [  3  0  4 ]          B [   2   0 ]
                                     C [   0   4 ]
                            
        [u1, u1] = 1·1 + 2·2 + 0·0 = 5
        [u1, u2] = 1·3 + 2·0 + 0·4 = 3   
        [u2, u1] = 3·1 + 0·2 + 4·0 = 3
        [u2, u2] = 3·3 + 0·0 + 4·4 = 25    
        """

        sq = (X**2) @ mask.T  # u1's squared ratings, summed over the items both u1 and u2 rated
        """
                 X ** 2                  mask.T
                  A  B  C                  u1  u2
            u1 [  1  4   0 ]          A [   1   1 ]
            u2 [  9  0  16 ]          B [   1   0 ]
                                      C [   0   1 ]
                            
            sq[u1, u2] = 1·1 + 4·0 + 0·1 =  1    
            sq[u2, u1] = 9·1 + 0·1 + 16·0 = 9  
            sq[u1, u1] = 1·1 + 4·1 + 0·0 =  5
            sq[u2, u2] = 9·1 + 0·0 + 16·1 = 25   
        """

        denom = np.sqrt(sq * sq.T)
        """
                   sq                    sq.T                  sq * sq.T
                  u1  u2                u1  u2                u1    u2
            u1 [  5   1 ]         u1 [  5   9 ]         u1 [  25     9 ]
            u2 [  9  25 ]         u2 [  1  25 ]         u2 [   9   625 ]
        """

        S = np.divide(nominator, denom, out=np.zeros_like(nominator), where=denom > 0)
        np.fill_diagonal(S, 1)  # [u1, u1] = 1

        return S

    def calc_top_k_predictions(S: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        u - user we predict for
        p - item
        v - neighbour: a user similar to u who rated p

        r(u, p) = R_mean[u] + nominator / denominator

        nominator = sum(Sim(u, v) * R_norm[v][p]) -> do similar users like p?
        denominator = sum(abs(Sim(u, v)))         -> essentially normalization over similarity

        [!] skipping v == u and R_norm[v][p] == np.nan
        """

        R_arr = R_norm.to_numpy(dtype=np.float64)
        mask = ~np.isnan(R_arr)  # True where rated
        np.fill_diagonal(S, 0)
        R_arr = np.nan_to_num(R_arr)  # unrated -> 0

        # ---

        nominator = S @ R_arr
        """
                S                             R
             u1    u2    u3                p1    p2
        u1 [  0    0.8  −0.2 ]        u1 [  1     0  ]
        u2 [ 0.8    0    0.5 ]        u2 [ 0.5   −1  ]
        u3 [−0.2   0.5    0  ]        u3 [  0     2  ]

        [u1, p1] = 0·1   + 0.8·0.5  + (−0.2)·0 =  0.4
        [u1, p2] = 0·0   + 0.8·(−1) + (−0.2)·2 = −1.2
        """

        denominator = np.abs(S) @ mask

        # rectify recommendations when few neighbors' ratings are taking place
        lambd = 2  # 1-5
        denominator += lambd
        """
        item A: 1 real neighbour (sim 0.3) who loved it
        
        without lam:  0.45 / 0.3       = +1.50
        with lam:     0.45 / (0.3 + 2) = +0.20

        item B: 10 real neighbours (sim 0.3 each) who liked it
        without lam:  3.0 / 3.0        = +1.00
        with lam:     3.0 / (3.0 + 2)  = +0.60
        
        A.without_lam > B.without_lam
        
        lambd is kinda of imaginary neighour who always gives the same ratings. 
        In this way it does not affect recommendations in the end of the day.
        But rectifies results with small number of neighbors
        """

        R = np.divide(nominator, denominator, out=np.zeros_like(nominator), where=denominator > 0)
        P = R_mean.to_numpy()[:, None] + R  # predicted ratings: add each user's mean to their row

        P[mask] = -np.inf  # never recommend items the user rated in train

        rows = R_norm.index.get_indexer(pd.Index(test_users))  # matrix row of each test user
        P = P[rows]

        top_k_cols = np.argsort(P, axis=1, descending=True)[:, :10]
        top_k_preds = R_norm.columns.to_numpy()[top_k_cols].tolist()
        top_k_scores = np.take_along_axis(P, top_k_cols, axis=1).tolist()

        return (top_k_preds, top_k_scores)

    S = calc_similarities()

    # shrink similarity by how many movies the two users both rated:
    # the more shared movies, the more we trust that they really have similar taste
    # 
    # shared movies         trust factor           sim 1.0 becomes
    #  2                2 / (2 + 20)   ≈ 0.09           0.09
    #  50               50 / (50 + 20)  ≈ 0.71          0.71
    #  200              200 / (200 + 20) ≈ 0.91         0.91
    #
    mask = R_norm.notna().to_numpy(dtype=np.float64)  # 1 where rated
    n_common = mask @ mask.T - 1  # n(u1, u2): items both rated. -1 just because it's more smooth version, no special explanations
    beta = 20  # how many shared movies you need before you trust a similarity
    S *= n_common / (n_common + beta)

    # filter out neighbors that aren't similar to the user
    np.fill_diagonal(S, 0)
    k = 50  # number of the most similar neighbours to each user to keep
    kth = -np.partition(-S, k - 1, axis=1)[:, k - 1 : k]  # k-th largest similarity per row
    S[S < kth] = 0

    top_k_predictions, top_k_scores = calc_top_k_predictions(S)

    users = []
    items = []
    ratings = []

    for i, user in enumerate(test_users):
        users.extend([user] * 10)
        items.extend(top_k_predictions[i])
        ratings.extend(top_k_scores[i])

    return pd.DataFrame({"user_id": users, "item_id": items, "rating": ratings})


def _empty_prediction() -> pd.DataFrame:
    return pd.DataFrame({"user_id": [], "item_id": [], "rating": []})
