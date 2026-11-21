import dataset

import metrics
import recommend


def main():
    movielens = dataset.load_movielens()
    time_threshold = movielens.ratings["timestamp"].quantile(0.8, interpolation="nearest")

    train_data = movielens.ratings[movielens.ratings["timestamp"] <= time_threshold]
    test_data = movielens.ratings[movielens.ratings["timestamp"] > time_threshold]

    measures = list()

    # remain only users that are presented in both train and test sets
    users_intersection = set(test_data["user_id"]) & set(train_data["user_id"])
    test_users = sorted(list(users_intersection))
    
    test_data = test_data[test_data["user_id"].isin(test_users)] #  keep only the test ratings from users who also have ratings in train_data (since metrics join left) 
    liked = test_data[test_data["rating"] >= 4] # remain only recommended items that user actually liked in test time (put at least rating 4)

    baseline_prediction = recommend.baseline(train_data, test_users)
    measures.append(
        metrics.measure(
            predictions=baseline_prediction,
            true_values=liked,
            all_values=train_data["item_id"],
            name="base_line",
            metrics=None,
            covered_items=train_data["item_id"],
        )
    )

    ease_prediction = recommend.ease(train_data, test_users)
    measures.append(
        metrics.measure(
            predictions=ease_prediction,
            true_values=liked,
            all_values=train_data["item_id"],
            name="ease",
            metrics=None,
            covered_items=train_data["item_id"],
        )
    )

    u2u_prediction = recommend.user2user_CF(train_data, test_users)
    measures.append(
        metrics.measure(
            predictions=u2u_prediction,
            true_values=liked,
            all_values=train_data["item_id"],
            name="u2u",
            metrics=None,
            covered_items=train_data["item_id"],
        )
    )

    for m in measures:
        print(m)


if __name__ == "__main__":
    main()
