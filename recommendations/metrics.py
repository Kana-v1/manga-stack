import pandas as pd
from copy import deepcopy

K = 10


def measure(
    predictions: pd.DataFrame,
    true_values: pd.DataFrame,
    all_values: pd.Series,
    name: str,
    metrics: pd.DataFrame | None,
    covered_items: pd.Series | None,
) -> pd.DataFrame:
    if metrics is None:
        metrics = pd.DataFrame(columns=["hit_rate@K", "coverage@K"])

    metrics.loc[name, "hit_rate@K"] = _metric_wrap(
        predictions=predictions,
        ground_truth=true_values,
        k=K,
        metric_by_user=_user_hr,
    )[0]

    if covered_items is not None:
        metrics.loc[name, "coverage@K"] = _coverage(predictions, K, all_values)

    return metrics


def _metric_wrap(
    predictions: pd.DataFrame,
    ground_truth: pd.DataFrame,
    k: int,
    metric_by_user,
) -> tuple[float, pd.Series]:
    """
    Prepare data for metric calculation (create dataframe with columns 'user_id', 'pred_list', 'gt_list').

    'predictions' contains
        a list of user ids ``user_id`` and
        a list or ratings ``rating``

    'pred_list' is a list of top-k recommendation ordered by relevance (most relevant is the first)
    'gt_list' is a list of items from tests data.
    Return mean metric value and dataframe with metric value for each user
    """
    top_k_predictions = _leave_top_k(predictions, k, "user_id", "rating")
    # prepare score lists
    predictions_grouped = (
        top_k_predictions.sort_values(["user_id", "rating"], ascending=[False, False])
        .groupby("user_id")["item_id"]
        .apply(list)
        .rename("pred_list")
    )

    gt_grouped = (
        ground_truth.groupby("user_id")["item_id"].apply(list).rename("gt_list")
    )
    to_compare = gt_grouped.to_frame().join(predictions_grouped, how="left")
    to_compare["pred_list"] = to_compare["pred_list"].apply(
        lambda x: x if isinstance(x, list) else []
    )
    # compute metric
    metric_by_user = to_compare.apply(metric_by_user, axis=1)

    return metric_by_user.mean(), metric_by_user


def _user_hr(row: pd.Series) -> int:
    """
    Calculate HitRate value.
    
    Hitrate  measures how many users got at least one useful recommendation. 
    A recommendation is useful if the user really watched it later, in the test period

    'row' contains
        a list of ground truth items in ``gt_items`` and
        a list of recommended items in ``pred_list``.
    """
    for item in row["pred_list"]:
        if item in row["gt_list"]:
            return 1

    return 0


def _coverage(predictions: pd.DataFrame, k: int, all_items: pd.Series) -> float:
    """
    Calculate coverage value (% of all items that took a place in the recommendation).

    'predictions' contains
        a list of user ids ``user_id`` and
        a list or ratings ``rating``
    'all_items' contains
        a list of item ids ``item_id``
    """
    top_k_predictions = set(
        _leave_top_k(predictions, k, "user_id", "rating")["item_id"].values
    )
    all_items_unique = set(all_items.unique())

    return len(top_k_predictions & all_items_unique) / len(all_items_unique)


def _leave_top_k(
    predictions: pd.DataFrame, k: int, group_by_col: str, order_by_col: str
) -> pd.DataFrame:
    """
    crop predictions to leave top-k recommendations for each user
    """
    if predictions.groupby(group_by_col)[group_by_col].count().max() <= k:
        return predictions

    cropped_pred = deepcopy(predictions)
    cropped_pred["rank"] = cropped_pred.groupby(group_by_col)[[order_by_col]].rank(
        method="first", ascending=False
    )

    cropped_pred = cropped_pred[cropped_pred["rank"] <= k].drop(columns=["rank"])
    return cropped_pred
