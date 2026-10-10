"""Historical evaluation separates supplied totals from withheld composition."""

from math import gamma

import numpy as np

from .stock_model import reconstruct, survival_matrix


def check_experiment_inputs(experiment, fields):
    allowed = {
        "A": {"initial_cohorts", "lifetime_prior"},
        "B": {"initial_cohorts", "lifetime_prior", "independent_additions"},
        "C": {"initial_cohorts", "lifetime_prior", "closing_totals"},
    }
    if experiment not in allowed or set(fields) - allowed[experiment]:
        raise ValueError("Held-out cohort information is not an allowed model input")
    if not {"initial_cohorts", "lifetime_prior"}.issubset(fields):
        raise ValueError("Initial conditions and priors must be declared")


def opening_survival(initial, reference, year, mean, shape=3, *, method="prior"):
    if method not in {"prior", "no-retirement"} or mean <= 0 or shape <= 0:
        raise ValueError("Invalid survival prior or method")
    if year <= reference or any(c > reference or q < 0 for c, q in initial.items()):
        raise ValueError("Invalid opening cohort experiment")
    scale = mean / gamma(1 + 1 / shape)
    return {
        c: q
        * (
            np.exp(-(((year - c) / scale) ** shape - ((reference - c) / scale) ** shape))
            if method == "prior"
            else 1.0
        )
        for c, q in initial.items()
    }


def conditional_history(
    initial, reference, totals, mean, shape=3, *, method="prior", additions=None
):
    """Only aggregate totals or independently supplied additions enter prediction."""
    if method not in {"prior", "no-retirement", "equilibrium"}:
        raise ValueError("Unknown historical method")
    if (
        not initial
        or sum(initial.values()) <= 0
        or any(c > reference or q < 0 for c, q in initial.items())
    ):
        raise ValueError("Invalid initial cohorts")
    if mean <= 0 or shape <= 0 or any(not np.isfinite(v) or v < 0 for v in totals.values()):
        raise ValueError("Invalid driver or prior")
    end = max(totals)
    if set(totals) != set(range(reference, end + 1)):
        raise ValueError("Annual driver is incomplete")
    mode = "inflow" if additions is not None else "stock"
    fields = [
        "initial_cohorts",
        "lifetime_prior",
        "independent_additions" if mode == "inflow" else "closing_totals",
    ]
    check_experiment_inputs("B" if mode == "inflow" else "C", fields)
    first = reference - 120 if method == "equilibrium" else min(initial)
    years = np.arange(first, end + 1)
    if method == "no-retirement":
        sf = survival_matrix(years.tolist(), np.full(len(years), 10000), distribution="fixed")
    else:
        sf = survival_matrix(
            years.tolist(),
            np.full(len(years), mean),
            distribution="weibull",
            shape=shape,
            conditional_year=None if method == "equilibrium" else reference,
        )
    stock = np.zeros(len(years))
    if method == "equilibrium":
        stock[:] = sf[reference - first]
    else:
        for c, q in initial.items():
            stock[c - first] = q
    stock *= totals[reference] / stock.sum()
    if additions is not None:
        if set(additions) != set(range(reference + 1, end + 1)):
            raise ValueError("Independent additions must cover all projected years")
        targets = np.r_[0.0, [additions[y] for y in range(reference + 1, end + 1)]]
    else:
        targets = np.array([totals[y] for y in range(reference, end + 1)])
    result = reconstruct(
        years=years,
        reference_year=reference,
        initial=stock,
        survival=sf,
        targets=targets,
        mode=mode,
        exit_policy="proportional" if mode == "stock" else "error",
    )
    return {
        int(y): dict(zip(map(int, years), row, strict=True))
        for y, row in zip(result.years, result.stock, strict=True)
    }


def score_cohorts(predicted, observed, year, *, total_is_input, tail_age=40):
    """Age metrics use dated support; caller must report undated/uncovered mass."""
    if (
        not predicted
        or not observed
        or any(c > year and v != 0 for d in (predicted, observed) for c, v in d.items())
    ):
        raise ValueError("Missing or future observed/predicted cohorts")
    low = min(set(predicted) | set(observed))
    cohorts = np.arange(low, year + 1)
    a = np.array([predicted.get(int(c), 0.0) for c in cohorts], float)
    b = np.array([observed.get(int(c), 0.0) for c in cohorts], float)
    if any((x < 0).any() or not np.isfinite(x).all() or x.sum() <= 0 for x in (a, b)):
        raise ValueError("Metrics require positive, finite dated distributions")
    p, q = a / a.sum(), b / b.sum()
    age = year - cohorts

    def quantile(w, prob):
        return float(age[::-1][np.searchsorted(np.cumsum(w[::-1]), prob)])

    bins = age // 5
    pb = np.bincount(bins, weights=p)
    qb = np.bincount(bins, weights=q)
    return dict(
        predicted_dated_stock=float(a.sum()),
        observed_dated_stock=float(b.sum()),
        stock_error=None if total_is_input else float(a.sum() - b.sum()),
        relative_stock_error=None if total_is_input else float((a.sum() - b.sum()) / b.sum()),
        total_variation=float(0.5 * np.abs(p - q).sum()),
        age_w1=float(np.abs(np.cumsum(p - q)).sum()),
        mean_age_bias=float(np.dot(age, p - q)),
        median_age_bias=quantile(p, 0.5) - quantile(q, 0.5),
        p90_age_bias=quantile(p, 0.9) - quantile(q, 0.9),
        five_year_bin_tv=float(0.5 * np.abs(pb - qb).sum()),
        tail_share_error=float((p - q)[age >= tail_age].sum()),
        tail_age=tail_age,
        total_stock_conditioned=total_is_input,
    )
