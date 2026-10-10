"""Constrained annual additions with exact stock anchors and fixed survival.

The optimization is convex: conditional survival and any proportional extra
exit fractions are fixed before fitting. Additional exits are not invented to
force agreement with reported inflows. SciPy HiGHS checks linear feasibility;
SLSQP minimizes a quadratic curvature objective on that feasible set.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import qr
from scipy.optimize import Bounds, LinearConstraint, linprog, lsq_linear, minimize

from .exceptions import DataValidationError
from .stock_model import CohortResult


def joint_horizon(stock_series, reference_year, end_year, timing):
    """Include the next stock anchor and full intersecting reporting windows."""
    following = [y for y in stock_series if y >= end_year]
    if not following:
        raise DataValidationError("Joint annualisation needs a stock anchor at/after end_year.")
    end = min(following)
    if timing["kind"] == "reported_periods":
        periods = timing["periods"]
        occupied, anchors = set(), set()
        for period in periods:
            window = set(range(period["start"], period["end"] + 1))
            if occupied & window or period["anchor"] in anchors:
                raise DataValidationError("Duplicate/overlapping reporting periods.")
            occupied.update(window)
            anchors.add(period["anchor"])
        selected = [p for p in periods if p["end"] > reference_year and p["start"] <= end]
        if any(p["start"] <= reference_year for p in selected):
            raise DataValidationError(
                "Joint annualisation cannot constrain a partial initial reporting period; "
                "align reference_year with a period end or supply an earlier initial stock."
            )
        if selected:
            end = max(end, max(p["end"] for p in selected))
        if set(range(reference_year + 1, end + 1)) - occupied:
            raise DataValidationError("Reporting windows do not cover the joint solve horizon.")
    if end > max(stock_series):
        raise DataValidationError("Complete reporting windows would require extrapolation.")
    return end


def _flow_constraints(series, years, timing):
    rows, targets, metadata = [], [], []
    if timing["kind"] == "sampled_annual":
        for anchor in sorted(series):
            if anchor not in years:
                continue
            row = (years == anchor).astype(float)
            rows.append(row)
            targets.append(series[anchor])
            metadata.append({"kind": "sampled_annual", "anchor": anchor, "years": [anchor]})
    else:
        for period in timing["periods"]:
            selected = (years >= period["start"]) & (years <= period["end"])
            if not selected.any():
                continue
            width = period["end"] - period["start"] + 1
            if selected.sum() != width or period["anchor"] not in series:
                raise DataValidationError("Incomplete/unknown addition reporting window.")
            rows.append(selected.astype(float) / width)
            targets.append(series[period["anchor"]])
            metadata.append(
                {
                    "kind": "reported_periods",
                    "anchor": period["anchor"],
                    "years": years[selected].tolist(),
                }
            )
    if not rows:
        raise DataValidationError("Joint annualisation needs an inflow observation in its horizon.")
    return np.array(rows), np.array(targets), metadata


def _independent_equalities(matrix, target):
    """Remove redundant rows only after feasibility of the full system is checked."""
    _, upper, pivots = qr(matrix.T, pivoting=True, mode="economic")
    rank = np.linalg.matrix_rank(upper)
    return matrix[pivots[:rank]], target[pivots[:rank]]


def fit_annual_additions(
    response,
    initial_stock,
    stock_targets,
    flow_matrix,
    flow_targets,
    reference,
    *,
    inflow_constraints,
    reference_weight,
    inflow_weight,
):
    """Fit nonnegative inflows; stocks are hard, conflicting inflows explicit.

    All quantities use one common stock scale. In penalized mode, incompatible
    inflow observations receive a declared quadratic penalty. The minimum L1
    rate discrepancy is also reported as a separate feasibility diagnostic.
    """
    scale = max(
        float(np.max(stock_targets)),
        float(np.max(flow_targets)),
        float(np.max(initial_stock)),
        1e-12,
    )
    stock_rhs = (stock_targets - initial_stock) / scale
    flow_rhs, reference = flow_targets / scale, reference / scale
    n, m = len(reference), len(flow_rhs)
    exact_a = np.vstack((response, flow_matrix))
    exact_b = np.r_[stock_rhs, flow_rhs]
    lp_options = {"primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9}
    feasible = linprog(
        np.zeros(n),
        A_eq=exact_a,
        b_eq=exact_b,
        bounds=(0, None),
        method="highs",
        options=lp_options,
    )
    if feasible.status not in (0, 2):
        raise DataValidationError(f"Joint feasibility solver failed: {feasible.message}")
    exact = feasible.success
    minimum_residual = 0.0
    if exact:
        equality, target = _independent_equalities(exact_a, exact_b)
    else:
        if inflow_constraints == "strict":
            raise DataValidationError(
                "Infeasible stock/inflow constraints under the configured initial cohorts, "
                "survival and fixed extra-exit fractions. Select penalized explicitly "
                "to retain stock anchors and report inflow discrepancies."
            )
        slack_equality = np.pad(response, ((0, 0), (0, m)))
        upper = np.vstack((np.c_[flow_matrix, -np.eye(m)], np.c_[-flow_matrix, -np.eye(m)]))
        bound = np.r_[flow_rhs, -flow_rhs]
        feasible = linprog(
            np.r_[np.zeros(n), np.ones(m)],
            A_eq=slack_equality,
            b_eq=stock_rhs,
            A_ub=upper,
            b_ub=bound,
            bounds=(0, None),
            method="highs",
            options=lp_options,
        )
        if not feasible.success:
            raise DataValidationError(f"Joint stock-only feasibility failed: {feasible.message}")
        minimum_residual = float(feasible.fun)
        equality, target = _independent_equalities(response, stock_rhs)
    constraints = [LinearConstraint(equality, target, target)]
    curvature = np.diff(np.eye(n), n=2, axis=0)

    def objective(x):
        bending, deviation = curvature @ x[:n], x[:n] - reference
        error = flow_matrix @ x - flow_rhs
        penalty = 0 if exact else inflow_weight * (error @ error)
        return bending @ bending + reference_weight * (deviation @ deviation) + penalty

    def gradient(x):
        result = np.zeros_like(x)
        result[:n] = 2 * (
            curvature.T @ (curvature @ x[:n]) + reference_weight * (x[:n] - reference)
        )
        if not exact:
            result += 2 * inflow_weight * flow_matrix.T @ (flow_matrix @ x - flow_rhs)
        return result

    # A tighter tolerance is needed for some nearly stationary declining stocks.
    # Retry only if the independent KKT certificate requires it; demanding this
    # tolerance universally can stall SLSQP on degenerate bound-active faces.
    start = feasible.x[:n]
    for ftol in (1e-13, 1e-15):
        optimized = minimize(
            objective,
            start,
            jac=gradient,
            method="SLSQP",
            bounds=Bounds(0, np.inf),
            constraints=constraints,
            options={"ftol": ftol, "maxiter": 2000},
        )
        if not optimized.success:
            raise DataValidationError(f"Joint smooth annual fit failed: {optimized.message}")
        values = optimized.x[:n]
        if (values < -1e-10).any():
            raise DataValidationError("Annual fit produced negative additions.")
        values = np.maximum(values, 0)
        stock_error = response @ values - stock_rhs
        errors = flow_matrix @ values - flow_rhs
        if np.max(np.abs(stock_error), initial=0) > 1e-8:
            raise DataValidationError("Annual fit did not preserve stock anchors.")
        if exact and np.max(np.abs(errors), initial=0) > 1e-8:
            raise DataValidationError("Annual fit did not preserve inflow constraints.")
        # Independently certify convex optimality including nonnegative bounds.
        active = np.flatnonzero(values < 1e-9)
        kkt_matrix = np.c_[equality.T, -np.eye(n)[:, active]]
        dual = lsq_linear(
            kkt_matrix,
            -gradient(values),
            method="bvls",
            tol=1e-12,
            bounds=(
                np.r_[np.full(len(target), -np.inf), np.zeros(len(active))],
                np.full(len(target) + len(active), np.inf),
            ),
        )
        stationarity = float(np.max(np.abs(kkt_matrix @ dual.x + gradient(values))))
        complementarity = float(np.max(np.abs(dual.x[len(target) :] * values[active]), initial=0))
        if dual.success and stationarity <= 2e-6 and complementarity <= 1e-8:
            break
        start = values
    else:
        raise DataValidationError(
            "Annual fit failed its independent convex optimality check: "
            f"stationarity={stationarity:.6g}, complementarity={complementarity:.6g}, "
            f"dual_success={dual.success}."
        )
    return values * scale, {
        "exact_inflow_constraints_feasible": exact,
        "inflow_constraint_policy": inflow_constraints,
        "minimum_sum_absolute_rate_residual": minimum_residual * scale,
        "actual_sum_absolute_rate_residual": float(np.abs(errors).sum() * scale),
        "stock_anchor_max_absolute_residual": float(np.abs(stock_error).max() * scale),
        "quantity_scale": scale,
        "reference_weight": reference_weight,
        "inflow_weight": inflow_weight,
        "objective": float(objective(optimized.x)),
        "iterations": int(optimized.nit),
        "final_solver_ftol": ftol,
        "kkt_stationarity_max": stationarity,
        "kkt_complementarity_max": complementarity,
        "solver": "SciPy HiGHS linear feasibility / SLSQP convex quadratic smoothing",
    }


def reconstruct_joint(
    *,
    baseline,
    survival,
    stock_series,
    flow_series,
    timing,
    reference_inflows,
    options,
    exit_policy="proportional",
):
    """Fit annual entries, conditionally retaining baseline extra-exit fractions."""
    years, cohorts = baseline.years, baseline.cohorts
    ref = int(np.flatnonzero(cohorts == years[0])[0])
    n = len(years)
    retention = np.ones(n)
    opening_survivors = baseline.stock[:-1].sum(axis=1) - baseline.natural_exit[1:]
    retention[1:] -= np.divide(
        baseline.additional_exit[1:],
        opening_survivors,
        out=np.zeros(n - 1),
        where=opening_survivors > 0,
    )
    if (retention < -1e-12).any() or (retention > 1 + 1e-12).any():
        raise DataValidationError("Invalid baseline additional-exit fractions.")
    retention = np.clip(retention, 0, 1)
    if exit_policy == "error":
        retention[:] = 1
    # Linear response of the stock to each future entrant, including fixed exits.
    initial = np.zeros_like(baseline.stock)
    initial[0] = baseline.stock[0]
    response = np.zeros((n, n - 1))
    for t in range(1, n):
        ratio = np.divide(
            survival[ref + t],
            survival[ref + t - 1],
            out=np.zeros(len(cohorts)),
            where=survival[ref + t - 1] > 0,
        )
        initial[t] = initial[t - 1] * ratio * retention[t]
        response[t] = response[t - 1] * ratio[ref + 1 :] * retention[t]
        response[t, t - 1] = 1
    anchors = [t for t, y in enumerate(years) if t and y in stock_series]
    if not anchors:
        raise DataValidationError("Joint reconstruction requires a future stock anchor.")
    flow_a, flow_b, flow_metadata = _flow_constraints(flow_series, years[1:], timing)
    inflows, diagnostics = fit_annual_additions(
        response[anchors],
        initial[anchors].sum(axis=1),
        np.array([stock_series[years[t]] for t in anchors]),
        flow_a,
        flow_b,
        reference_inflows[1:],
        **options,
    )
    stock = np.zeros_like(baseline.stock)
    stock[0] = baseline.stock[0]
    natural, additional, balance = [np.full(n, np.nan) for _ in range(3)]
    for t in range(1, n):
        ratio = np.divide(
            survival[ref + t],
            survival[ref + t - 1],
            out=np.zeros(len(cohorts)),
            where=survival[ref + t - 1] > 0,
        )
        survivors = stock[t - 1] * ratio
        natural[t] = stock[t - 1].sum() - survivors.sum()
        additional[t] = survivors.sum() * (1 - retention[t])
        stock[t] = survivors * retention[t]
        stock[t, ref + t] = inflows[t - 1]
        balance[t] = (
            stock[t - 1].sum() + inflows[t - 1] - natural[t] - additional[t] - stock[t].sum()
        )
    predicted = flow_a @ inflows
    for meta, target, actual in zip(flow_metadata, flow_b, predicted, strict=True):
        meta.update(
            target_rate=float(target),
            reconstructed_rate=float(actual),
            rate_residual=float(actual - target),
        )
        if meta["kind"] == "reported_periods":
            width = len(meta["years"])
            meta.update(
                target_total=float(target * width),
                reconstructed_total=float(actual * width),
                total_residual=float((actual - target) * width),
            )
    diagnostics.update(
        flow_constraints=flow_metadata,
        stock_anchors=[
            {
                "year": int(years[t]),
                "target": float(stock_series[years[t]]),
                "reconstructed": float(stock[t].sum()),
            }
            for t in anchors
        ],
        solve_years=years.tolist(),
        annual_inflows=inflows.tolist(),
        additional_exit_fractions=(1 - retention).tolist(),
        additional_exit_assumption=(
            "no additional exits"
            if exit_policy == "error"
            else "fixed fractions from linear-stock baseline; proportional "
            "across naturally surviving cohorts, not fitted"
        ),
        baseline_curvature_l2=float(np.linalg.norm(np.diff(baseline.inflow[1:], n=2))),
        fitted_curvature_l2=float(np.linalg.norm(np.diff(inflows, n=2))),
    )
    return CohortResult(
        years, cohorts, stock, np.r_[np.nan, inflows], natural, additional, balance
    ), diagnostics
