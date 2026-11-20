"""Constrained annual additions with exact stock anchors and fixed survival.

The optimization is convex: conditional survival and any proportional extra
exit fractions are fixed before fitting. Additional exits are not invented to
force agreement with reported inflows. SciPy HiGHS checks linear feasibility;
pinned OSQP minimizes a quadratic curvature objective on that feasible set.
"""

from __future__ import annotations

import numpy as np
import osqp
from scipy.linalg import qr
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize
from scipy.sparse import csc_matrix, eye, vstack

from .exceptions import DataValidationError
from .stock_model import reconstruct


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
    """Describe which annual additions must match each reported flow value."""
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
        # A reported period rate constrains the mean of the years in that period.
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


def _check_annual_fit_feasibility(response, stock_rhs, flow_matrix, flow_rhs, policy):
    """Find which reported values can be matched with nonnegative additions."""
    n, m = response.shape[1], len(flow_rhs)
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
    if feasible.success:
        return exact_a, exact_b, True, 0.0

    if policy == "strict":
        raise DataValidationError(
            "Infeasible stock/inflow constraints under the configured initial cohorts, "
            "survival and fixed extra-exit fractions. Select penalized explicitly "
            "to retain stock anchors and report inflow discrepancies."
        )
    # One slack value per flow observation measures its absolute mismatch.
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
    return response, stock_rhs, False, float(feasible.fun)


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
    """Fit nonnegative annual additions that match the reported stock.

    Each column of response gives the stock left from one year's additions.
    Each row corresponds to a year with a reported stock value. Penalized mode
    allows a mismatch in reported additions and records the smallest possible
    sum of absolute mismatches alongside the actual mismatch of the smooth fit.
    """
    # Work in relative units to handle fleets of very different sizes.
    scale = max(
        float(np.max(stock_targets)),
        float(np.max(flow_targets)),
        float(np.max(initial_stock)),
        1e-12,
    )
    stock_rhs = (stock_targets - initial_stock) / scale
    flow_rhs, reference = flow_targets / scale, reference / scale
    required, required_values, exact, minimum_residual = _check_annual_fit_feasibility(
        response, stock_rhs, flow_matrix, flow_rhs, inflow_constraints
    )
    equality, target = _independent_equalities(required, required_values)
    n = len(reference)

    # Penalize changes in the growth rate, while also staying close to the starting estimate.
    curvature = np.diff(np.eye(n), n=2, axis=0)
    hessian = curvature.T @ curvature + reference_weight * np.eye(n)
    linear = -2 * reference_weight * reference
    if not exact:
        hessian += inflow_weight * flow_matrix.T @ flow_matrix
        linear -= 2 * inflow_weight * flow_matrix.T @ flow_rhs
    qp_feasible = linprog(
        np.zeros(n),
        A_eq=required,
        b_eq=required_values,
        bounds=(0, None),
        method="highs",
    )
    if not qp_feasible.success:
        raise DataValidationError(f"Joint QP feasibility failed: {qp_feasible.message}")
    # Give small and large reported values comparable weight in the solver's checks.
    equality_scale = 1 / np.maximum(np.abs(target), 1e-6)
    constraints = vstack(
        (csc_matrix(equality * equality_scale[:, None]), eye(n, format="csc")),
        format="csc",
    )
    scaled_target = target * equality_scale
    lower = np.r_[scaled_target, np.zeros(n)]
    upper = np.r_[scaled_target, np.full(n, np.inf)]

    def objective(x):
        """Score the smoothness of the additions and their fit to the inputs."""
        bending, deviation = curvature @ x, x - reference
        error = flow_matrix @ x - flow_rhs
        penalty = 0 if exact else inflow_weight * (error @ error)
        return bending @ bending + reference_weight * (deviation @ deviation) + penalty

    def solve_qp(tolerance, polishing):
        """Start OSQP from a feasible path found by the linear solver."""
        solver = osqp.OSQP()
        solver.setup(
            P=csc_matrix(2 * hessian),
            q=linear,
            A=constraints,
            l=lower,
            u=upper,
            eps_abs=tolerance,
            eps_rel=tolerance,
            eps_prim_inf=1e-10,
            eps_dual_inf=1e-10,
            max_iter=1_000_000,
            polishing=polishing,
            scaled_termination=True,
            adaptive_rho_interval=25,
            verbose=False,
        )
        solver.warm_start(x=qp_feasible.x)
        return solver.solve(raise_error=False)

    solver_tolerance = 1e-10
    optimized = solve_qp(solver_tolerance, True)
    if optimized.info.status_val not in (1, 2):
        # HiGHS has already certified feasibility. Very small stock anchors relative
        # to the catalogue maximum can make OSQP's infeasibility heuristic trigger
        # at the tighter tolerance, so retry at the independently enforced residual.
        solver_tolerance = 1e-8
        optimized = solve_qp(solver_tolerance, False)
    osqp_values = np.asarray(optimized.x) if optimized.x is not None else np.full(n, np.nan)
    osqp_equality_error = equality @ osqp_values - target
    osqp_valid = (
        np.isfinite(osqp_values).all()
        and osqp_values.min() >= -1e-9
        and np.max(np.abs(osqp_equality_error), initial=0) <= 1e-8
        and optimized.info.dual_res <= 2e-6
        and optimized.info.prim_res <= 1e-8
    )
    if not osqp_valid and exact:
        raise DataValidationError(
            "Joint convex QP failed its independently checked constraints: "
            f"status={optimized.info.status}, minimum={osqp_values.min():.6g}, "
            f"equality_residual={np.max(np.abs(osqp_equality_error)):.6g}, "
            f"primal_residual={optimized.info.prim_res:.6g}, "
            f"dual_residual={optimized.info.dual_res:.6g}."
        )
    if osqp_valid:
        values = np.maximum(osqp_values, 0)
        stationarity = float(optimized.info.dual_res)
        solver_primal_residual = float(optimized.info.prim_res)
        iterations = int(optimized.info.iter)
        solver_status = optimized.info.status
        solver_name = "SciPy HiGHS feasibility / OSQP 1.0.4 convex quadratic smoothing"
    else:
        fallback = minimize(
            objective,
            qp_feasible.x,
            jac=lambda x: 2 * hessian @ x + linear,
            constraints=LinearConstraint(equality, target, target),
            bounds=Bounds(0, np.inf),
            method="SLSQP",
            options={"ftol": 1e-15, "maxiter": 10_000, "disp": False},
        )
        values = np.asarray(fallback.x)
        equality_error = equality @ values - target
        if (
            not fallback.success
            or not np.isfinite(values).all()
            or values.min() < -1e-9
            or np.max(np.abs(equality_error), initial=0) > 1e-8
        ):
            raise DataValidationError(
                "Penalized joint QP failed OSQP and SLSQP fallback: "
                f"osqp={optimized.info.status}; slsqp={fallback.message}"
            )
        values = np.maximum(values, 0)
        gradient = 2 * hessian @ values + linear
        free = values > 1e-9
        multipliers = np.linalg.lstsq(equality[:, free].T, -gradient[free], rcond=None)[0]
        reduced_gradient = gradient + equality.T @ multipliers
        stationarity = float(
            max(
                np.max(np.abs(reduced_gradient[free]), initial=0),
                np.max(np.maximum(0, -reduced_gradient[~free]), initial=0),
            )
        )
        solver_primal_residual = float(np.max(np.abs(equality_error), initial=0))
        iterations = int(fallback.nit)
        solver_status = "solved"
        solver_tolerance = None
        solver_name = "SciPy HiGHS feasibility / SciPy SLSQP penalized-QP fallback"
    # Check all reported values, including constraints the solver omitted as redundant.
    stock_error = response @ values - stock_rhs
    errors = flow_matrix @ values - flow_rhs
    if np.max(np.abs(stock_error), initial=0) > 1e-8:
        raise DataValidationError("Annual fit did not preserve stock anchors.")
    if exact and np.max(np.abs(errors), initial=0) > 1e-8:
        raise DataValidationError("Annual fit did not preserve inflow constraints.")
    primal_residual = float(np.max(np.abs(equality @ values - target), initial=0))
    if stationarity > 2e-6 or primal_residual > 1e-8:
        raise DataValidationError(
            "Annual fit failed its QP certificate: "
            f"dual_residual={stationarity:.6g}, primal_residual={primal_residual:.6g}, "
            f"objective={objective(values):.6g}, minimum={values.min():.6g}, "
            f"iterations={iterations}."
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
        "objective": float(objective(values)),
        "iterations": iterations,
        "kkt_stationarity_max": stationarity,
        "primal_residual_max": primal_residual,
        "solver_primal_residual_max": solver_primal_residual,
        "solver_status": solver_status,
        "solver_certificate": "independent residual checks passed",
        "solver_tolerance": solver_tolerance,
        "constraint_scale_min": float(equality_scale.min()),
        "constraint_scale_max": float(equality_scale.max()),
        "solver": solver_name,
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
    """Fit annual additions and project the result through FLODyM.

    When early retirements are allowed, keep the yearly fractions from the
    stock-driven starting estimate fixed during the fit.
    """
    years, cohorts = baseline.years, baseline.cohorts
    ref = int(np.flatnonzero(cohorts == years[0])[0])
    n = len(years)
    # Calculate the fraction remaining after early retirement in each baseline year.
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
    # Track survivors from the opening stock and from each future year's additions.
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
    # Only the years reported by the IAM are fixed stock targets in the joint fit.
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
    # Apply the same additional-retirement fractions in the FLODyM projection.
    result = reconstruct(
        years=cohorts,
        reference_year=years[0],
        initial=baseline.stock[0],
        survival=survival,
        targets=np.r_[0.0, inflows],
        mode="inflow",
        exit_policy="error",
        removal_share=1 - retention[1:],
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
                "reconstructed": float(result.stock[t].sum()),
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
    return result, diagnostics
