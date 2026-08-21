"""
/*
 * PGMcpp : PRIMED Grid Modelling (in C++)
 * Copyright 2023 (C)
 * 
 * Jonathan Racine, Northern Energy Innovation
 * email:  jracine@yukonu.ca
 * 
 * Redistribution and use in source and binary forms, with or without modification,
 * are permitted provided that the following conditions are met:
 * 
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 * 3. Neither the name of the copyright holder nor the names of its contributors
 *    may be used to endorse or promote products derived from this software without
 *    specific prior written permission.
 * 
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 *  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 *  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 *  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 *  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 *  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 *  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 *  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 *  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 *  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 *  POSSIBILITY OF SUCH DAMAGE.
 * 
 *  CONTINUED USE OF THIS SOFTWARE CONSTITUTES ACCEPTANCE OF THESE TERMS.
 *
 */

Run the configured Paulatuk PGMcpp case matrix and combine summaries.


Original software author: Anthony Truelove, MASc, P.Eng.
Project adaptation and modifications: Jonathan Racine, Northern Energy
Innovation, 2026.

Economic treatment:
    - Wind-turbine capital is incurred once; no turbine replacement is modelled.
    - Powerline capital is incurred once and is not bundled with the turbine.
    - Wind and BESS O&M are fixed annual costs, not energy-throughput costs.
    - The terminal BESS receives a discounted residual-value credit based on
      the fraction of useful SOH remaining above the replacement threshold.

Last edited: 2026-08-21.
"""

import csv
import itertools
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# =============================================================================
# BATCH CASE SELECTION
# =============================================================================
LOAD_GROWTH_CASES = [0.03, 0.08, 0.666]
FUEL_ESCALATION_CASES = [0.0446]
POWERLINE_DISTANCE_CASES_KM = [2.8431, 5.2333, 3.780]
CONTROL_MODES_TO_RUN = ["PSIS"]

# Number of independent PGMcpp cases to run simultaneously.
# Set this lower if RAM becomes the limiting factor.
MAX_PARALLEL_CASES = 9


def number_tag(value, decimal_places):
    """Return a filesystem-safe fixed-decimal number."""
    return f"{value:.{decimal_places}f}".replace("-", "m").replace(".", "p")


def make_case_name(control_mode, load_growth, fuel_escalation, distance_km):
    """Build a deterministic filesystem-safe name for one batch case."""
    return (
        f"{control_mode.lower()}"
        f"_growth_{number_tag(100.0 * load_growth, 2)}pct"
        f"_fuel_{number_tag(100.0 * fuel_escalation, 2)}pct"
        f"_line_{number_tag(distance_km, 4)}km"
    )

# The parent process launches this same file once per case. Each child receives
# one combination through environment variables and executes the model below.


if __name__ == "__main__" and os.environ.get("PAULATUK_BATCH_CHILD") != "1":
    case_matrix = list(
        itertools.product(
            LOAD_GROWTH_CASES,
            FUEL_ESCALATION_CASES,
            POWERLINE_DISTANCE_CASES_KM,
            CONTROL_MODES_TO_RUN,
        )
    )
    script_path = Path(__file__).resolve()
    batch_results_dir = script_path.parent / "results" / "paulatuk_all_cases"
    batch_results_dir.mkdir(parents=True, exist_ok=True)
    temporary_summary_dir = batch_results_dir / "_temporary_case_summaries"
    temporary_summary_dir.mkdir(parents=True, exist_ok=True)
    completed_summaries = []
    failed_cases = []
    worker_count = min(MAX_PARALLEL_CASES, len(case_matrix))
    print(f"Running {len(case_matrix)} Paulatuk cases with " f"{worker_count} parallel workers.")

    def run_case(case_number, case_values):
        """Launch one batch case in a child Python process."""
        (
            load_growth,
            fuel_escalation,
            distance_km,
            control_mode,
        ) = case_values
        case_name = make_case_name(
            control_mode,
            load_growth,
            fuel_escalation,
            distance_km,
        )
        summary_path = temporary_summary_dir / f"{case_name}.csv"
        print(
            f"[START {case_number}/{len(case_matrix)}] {case_name}",
            flush=True,
        )
        child_environment = os.environ.copy()
        child_environment.update(
            {
                "PAULATUK_BATCH_CHILD": "1",
                "PAULATUK_LOAD_GROWTH": str(load_growth),
                "PAULATUK_FUEL_ESCALATION": str(fuel_escalation),
                "PAULATUK_LINE_DISTANCE_KM": str(distance_km),
                "PAULATUK_CONTROL_MODE": control_mode,
                "PAULATUK_SUMMARY_PATH": str(summary_path),
            }
        )
        result = subprocess.run(
            [sys.executable, str(script_path)],
            env=child_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return case_number, case_name, summary_path, result
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(run_case, case_number, case_values)
            for case_number, case_values in enumerate(case_matrix, start=1)
        ]
        for future in as_completed(futures):
            case_number, case_name, summary_path, result = future.result()
            if result.returncode == 0 and summary_path.exists():
                completed_summaries.append((case_number, summary_path))
                print(
                    f"[DONE  {case_number}/{len(case_matrix)}] {case_name}",
                    flush=True,
                )
            else:
                failed_cases.append(
                    {
                        "case_name": case_name,
                        "return_code": result.returncode,
                    }
                )
                print(
                    f"[FAIL  {case_number}/{len(case_matrix)}] "
                    f"{case_name} (return code {result.returncode})",
                    file=sys.stderr,
                    flush=True,
                )
                if result.stderr:
                    print(result.stderr, file=sys.stderr, flush=True)
    master_rows = []
    for _case_number, summary_path in sorted(completed_summaries):
        with summary_path.open("r", newline="", encoding="utf-8") as file:
            master_rows.extend(csv.DictReader(file))
    master_summary_csv = batch_results_dir / "all_cases_summary.csv"
    with master_summary_csv.open("w", newline="", encoding="utf-8") as file:
        if master_rows:
            writer = csv.DictWriter(file, fieldnames=list(master_rows[0]))
            writer.writeheader()
            writer.writerows(master_rows)
    if failed_cases:
        failure_csv = batch_results_dir / "failed_cases.csv"
        with failure_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(failed_cases[0]))
            writer.writeheader()
            writer.writerows(failed_cases)
    else:
        failure_csv = batch_results_dir / "failed_cases.csv"
        if failure_csv.exists():
            failure_csv.unlink()

    # Individual summaries are only intermediate files; retain the master CSV.
    shutil.rmtree(temporary_summary_dir, ignore_errors=True)
    print("=" * 72)
    print(f"Successful cases: {len(completed_summaries)}/{len(case_matrix)}")
    print(f"Master summary: {master_summary_csv}")
    if failed_cases:
        print(f"Failed-case log: {failure_csv}")
        sys.exit(1)
    sys.exit(0)

# Values used by a batch child process.
LOAD_GROWTH = float(os.environ["PAULATUK_LOAD_GROWTH"])
FUEL_ESCALATION = float(os.environ["PAULATUK_FUEL_ESCALATION"])
POWERLINE_DISTANCE_KM = float(os.environ["PAULATUK_LINE_DISTANCE_KM"])
CONTROL_MODE = os.environ["PAULATUK_CONTROL_MODE"].upper()

# =============================================================================
# PATHS
# =============================================================================
PROJECTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECTS_DIR.parent
BINDINGS_DIR = ROOT_DIR / "pybindings" / "precompiled_bindings"
LOAD_DIR = ROOT_DIR / "data" / "test" / "electrical_load"
RESOURCE_DIR = ROOT_DIR / "data" / "test" / "resources"
RESULTS_DIR = PROJECTS_DIR / "results" / "paulatuk_all_cases"
LOAD_FILES = {
    0.03: LOAD_DIR / "paulatuk_load_20yr_growth_3pct_pgmcpp.csv",
    0.08: LOAD_DIR / "paulatuk_load_20yr_growth_8pct_pgmcpp.csv",
    0.666: LOAD_DIR / "paulatuk_feeder_load_20yr_nonlinear_pgmcpp.csv",
}
LOAD_CSV = LOAD_FILES[LOAD_GROWTH]
WIND_RESOURCE_CSV = RESOURCE_DIR / "wind_resource_20yr_pgmcpp_full_year_mps.csv"
WIND_NORMALIZED_CSV = Path(
    r"C:\Users\jracine\Desktop\PGMcpp_NEI_version\data\test"
    r"\normalized_production\ie0124_paulatuk_wind_normalized_20yr_1min.csv"
)
sys.path.insert(0, str(BINDINGS_DIR))
import PGMcpp  # noqa: E402 - binding path must be configured first

# =============================================================================
# SYSTEM PARAMETERS
# =============================================================================
DIESEL_CAPACITIES_KW = [250.0, 400.0, 412.0]
DIESEL_MINIMUM_LOAD_RATIO = 0.50
WIND_CAPACITY_KW = 1000.0
WIND_DESIGN_SPEED_MS = 14.0
WIND_FIRMNESS_FACTOR = 0.0

# Deliberately exceeds the study horizon so PGMcpp does not apply its default
# 90,000-running-hour production-asset replacement to the wind turbine.
WIND_REPLACEMENT_RUNNING_HOURS = 1.0e12
BESS_POWER_KW = 1000.0
BESS_ENERGY_KWH = 2000.0
BESS_REPLACEMENT_SOH = 0.80
FIRM_DISPATCH_RATIO = 0.0
LOAD_RESERVE_RATIO = 0.10

# PSIS controller settings. These are ignored in LOAD_FOLLOWING mode.
PSIS_DIESEL_ON_SOC = 0.10
PSIS_DIESEL_OFF_SOC = 0.89
PSIS_WIND_SHUTDOWN_MARGIN_RATIO = 0.00
PSIS_WIND_SHUTDOWN_PERSISTENCE_HR = 1 / 60
DIESEL_MINIMUM_RUNTIME_HR = 1.0
DIESEL_CYCLE_CHARGING_SETPOINT = 0.50
FUEL_COST_CAD_PER_L = 2.58
NOMINAL_INFLATION_ANNUAL = 0.0222
NOMINAL_DISCOUNT_ANNUAL = 0.05
REAL_DISCOUNT_ANNUAL = (1.0 + NOMINAL_DISCOUNT_ANNUAL) / (1.0 + NOMINAL_INFLATION_ANNUAL) - 1.0

# =============================================================================
# COSTS
# =============================================================================
USD_TO_CAD = 1.40
REMOTE_FACTOR = 1.99
CONTINGENCY_FACTOR = 1.30
POWERLINE_COST_CAD_PER_KM = 1_500_000
WIND_CAPITAL_COST_CAD = (
    2256.06 * WIND_CAPACITY_KW * REMOTE_FACTOR * USD_TO_CAD
)
POWERLINE_CAPITAL_COST_CAD = (
    POWERLINE_COST_CAD_PER_KM
    * POWERLINE_DISTANCE_KM
    * CONTINGENCY_FACTOR
)
BESS_CAPITAL_COST_CAD = 1659.39 * BESS_ENERGY_KWH * USD_TO_CAD * REMOTE_FACTOR

# Fixed O&M source values [USD/kW-yr]
WIND_FIXED_OM_USD_PER_KW_YR = 38.627
BESS_FIXED_OM_USD_PER_KW_YR = 37.522
WIND_FIXED_OM_ANNUAL_CAD = (
    WIND_FIXED_OM_USD_PER_KW_YR
    * USD_TO_CAD
    * REMOTE_FACTOR
    * WIND_CAPACITY_KW
)
BESS_FIXED_OM_ANNUAL_CAD = (
    BESS_FIXED_OM_USD_PER_KW_YR
    * USD_TO_CAD
    * REMOTE_FACTOR
    * BESS_POWER_KW
)


def present_value_fixed_annual_cost(annual_cost_cad, n_years, real_discount):
    """Return present value of a real annual cost paid at each year end."""
    whole_years = int(n_years)
    partial_year = n_years - whole_years
    present_value_cad = sum(
        annual_cost_cad / (1.0 + real_discount) ** year
        for year in range(1, whole_years + 1)
    )
    if partial_year > 1.0e-9:
        present_value_cad += (
            annual_cost_cad
            * partial_year
            / (1.0 + real_discount) ** n_years
        )
    return present_value_cad


def terminal_bess_residual_value(
    capital_cost_cad,
    final_soh,
    replacement_soh,
    horizon_years,
    real_discount,
):
    """Return terminal BESS residual value and its present value.

    Remaining useful life is approximated linearly over the usable SOH range
    from 1.0 down to the replacement threshold. The terminal value is then
    discounted from the end of the study to the initial year.
    """
    usable_soh_range = 1.0 - replacement_soh
    if usable_soh_range <= 0.0:
        raise ValueError("BESS replacement SOH must be less than 1.0")
    remaining_life_fraction = (
        (final_soh - replacement_soh) / usable_soh_range
    )
    remaining_life_fraction = max(0.0, min(1.0, remaining_life_fraction))
    terminal_value_cad = capital_cost_cad * remaining_life_fraction
    present_value_cad = terminal_value_cad / (
        (1.0 + real_discount) ** horizon_years
    )
    return remaining_life_fraction, terminal_value_cad, present_value_cad


def capital_recovery_factor(real_discount, n_years):
    """Return the capital-recovery factor for the economic horizon."""
    if n_years <= 0.0:
        raise ValueError("Economic horizon must be positive")
    if abs(real_discount) < 1.0e-12:
        return 1.0 / n_years
    growth = (1.0 + real_discount) ** n_years
    return real_discount * growth / (growth - 1.0)

# =============================================================================
# CASE SETUP
# =============================================================================
CASE_NAME = make_case_name(
    CONTROL_MODE,
    LOAD_GROWTH,
    FUEL_ESCALATION,
    POWERLINE_DISTANCE_KM,
)
SUMMARY_CSV = Path(os.environ["PAULATUK_SUMMARY_PATH"])
SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
CASE_DIR = RESULTS_DIR / CASE_NAME
CASE_DIR.mkdir(parents=True, exist_ok=True)
print("Paulatuk PGMcpp batch case")
print("-" * 72)
print(f"Case name:          {CASE_NAME}")
print(f"Controller:         {CONTROL_MODE}")
print(f"Load growth:        {LOAD_GROWTH:.0%}/yr")
print(f"Path length:        {POWERLINE_DISTANCE_KM:.4f} km")
print(f"Fuel escalation:    {FUEL_ESCALATION:.0%}/yr")
print(f"Load CSV:           {LOAD_CSV}")
print(f"Wind resource CSV:  {WIND_RESOURCE_CSV}")
print(f"Wind normalized CSV:{WIND_NORMALIZED_CSV}")
print(f"Output folder:      {CASE_DIR}")
print(f"Wind fixed O&M:     {WIND_FIXED_OM_ANNUAL_CAD:,.2f} CAD/yr")
print(f"BESS fixed O&M:     {BESS_FIXED_OM_ANNUAL_CAD:,.2f} CAD/yr")
print(f"Powerline CAPEX:    {POWERLINE_CAPITAL_COST_CAD:,.2f} CAD")
print("-" * 72)

# =============================================================================
# BUILD MODEL
# =============================================================================
CONTROL_MODES = {
    "PSIS": PGMcpp.ControlMode.PSIS,
    "LOAD_FOLLOWING": PGMcpp.ControlMode.LOAD_FOLLOWING,
}
model_inputs = PGMcpp.ModelInputs()
model_inputs.path_2_electrical_load_time_series = str(LOAD_CSV)
model_inputs.control_mode = CONTROL_MODES[CONTROL_MODE]
model_inputs.firm_dispatch_ratio = FIRM_DISPATCH_RATIO
model_inputs.load_reserve_ratio = LOAD_RESERVE_RATIO
model = PGMcpp.Model(model_inputs)
if CONTROL_MODE == "PSIS":
    model.controller.psis_diesel_on_soc = PSIS_DIESEL_ON_SOC
    model.controller.psis_diesel_off_soc = PSIS_DIESEL_OFF_SOC
    model.controller.psis_wind_shutdown_margin_ratio = PSIS_WIND_SHUTDOWN_MARGIN_RATIO
    model.controller.psis_wind_shutdown_persistence_hrs = PSIS_WIND_SHUTDOWN_PERSISTENCE_HR
wind_resource_key = 0
model.addResource(PGMcpp.RenewableType.WIND, str(WIND_RESOURCE_CSV), wind_resource_key)

# =============================================================================
# DIESEL FLEET
# =============================================================================
for capacity_kw in DIESEL_CAPACITIES_KW:
    diesel = PGMcpp.DieselInputs()
    diesel.combustion_inputs.production_inputs.capacity_kW = capacity_kw
    diesel.combustion_inputs.production_inputs.is_sunk = True
    diesel.combustion_inputs.production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
    diesel.combustion_inputs.production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
    diesel.combustion_inputs.fuel_mode = PGMcpp.FuelMode.FUEL_MODE_LINEAR
    diesel.combustion_inputs.nominal_fuel_escalation_annual = FUEL_ESCALATION
    diesel.combustion_inputs.cycle_charging_setpoint = DIESEL_CYCLE_CHARGING_SETPOINT
    diesel.fuel_cost_L = FUEL_COST_CAD_PER_L
    diesel.minimum_load_ratio = DIESEL_MINIMUM_LOAD_RATIO
    diesel.minimum_runtime_hrs = DIESEL_MINIMUM_RUNTIME_HR
    model.addDiesel(diesel)

# =============================================================================
# WIND
# =============================================================================
wind = PGMcpp.WindInputs()
wind.renewable_inputs.production_inputs.capacity_kW = WIND_CAPACITY_KW
wind.renewable_inputs.production_inputs.is_sunk = False
wind.renewable_inputs.production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
wind.renewable_inputs.production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
wind.renewable_inputs.production_inputs.replace_running_hrs = (
    WIND_REPLACEMENT_RUNNING_HOURS
)
wind.renewable_inputs.production_inputs.path_2_normalized_production_time_series = str(
    WIND_NORMALIZED_CSV
)
wind.resource_key = wind_resource_key
wind.firmness_factor = WIND_FIRMNESS_FACTOR

# When a normalized production time series is supplied above, PGMcpp uses it
# directly and bypasses this cubic wind-speed production model.
wind.design_speed_ms = WIND_DESIGN_SPEED_MS
wind.power_model = PGMcpp.WindPowerProductionModel.WIND_POWER_CUBIC
wind.capital_cost = WIND_CAPITAL_COST_CAD

# Fixed annual O&M is added after the PGMcpp run. Setting this to zero prevents
# PGMcpp from converting it into a variable cost on all wind production.
wind.operation_maintenance_cost_kWh = 0.0
model.addWind(wind)

# =============================================================================
# LI-ION BESS
# =============================================================================
bess = PGMcpp.LiIonInputs()
bess.storage_inputs.power_capacity_kW = BESS_POWER_KW
bess.storage_inputs.energy_capacity_kWh = BESS_ENERGY_KWH
bess.storage_inputs.is_sunk = False
bess.storage_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
bess.storage_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
bess.power_degradation_flag = False
bess.replace_SOH = BESS_REPLACEMENT_SOH
bess.init_SOC = 0.20
bess.min_SOC = 0.10
bess.hysteresis_SOC = 0.89
bess.max_SOC = 0.90
bess.charging_efficiency = 0.97
bess.discharging_efficiency = 0.97
bess.capital_cost = BESS_CAPITAL_COST_CAD

# Fixed annual O&M is added after the PGMcpp run. Setting this to zero prevents
# PGMcpp from charging maintenance on both BESS charging and discharging.
bess.operation_maintenance_cost_kWh = 0.0
model.addLiIon(bess)

# =============================================================================
# RUN
# =============================================================================
print("Running PGMcpp...", flush=True)
model.run()
print("PGMcpp run complete.", flush=True)

# Retrieve the actual Li-ion asset owned by the model. The ``bess`` variable
# above is only the LiIonInputs structure and does not contain run results.
bess_asset = model.storage_ptr_vec[0]

# =============================================================================
# ECONOMIC ADJUSTMENTS
# =============================================================================
# PGMcpp handles diesel fuel, wind capital, BESS capital, and BESS replacement
# costs internally. Costs that PGMcpp cannot represent as intended are applied
# here: one-time line CAPEX, fixed annual O&M, and terminal BESS residual value.
model_years = float(model.electrical_load.n_years)
economic_horizon_years = model_years
wind_fixed_om_npc_cad = present_value_fixed_annual_cost(
    WIND_FIXED_OM_ANNUAL_CAD,
    model_years,
    REAL_DISCOUNT_ANNUAL,
)
bess_fixed_om_npc_cad = present_value_fixed_annual_cost(
    BESS_FIXED_OM_ANNUAL_CAD,
    model_years,
    REAL_DISCOUNT_ANNUAL,
)
(
    bess_remaining_life_fraction,
    bess_terminal_residual_value_cad,
    bess_residual_value_pv_cad,
) = terminal_bess_residual_value(
    BESS_CAPITAL_COST_CAD,
    bess_asset.SOH,
    BESS_REPLACEMENT_SOH,
    economic_horizon_years,
    REAL_DISCOUNT_ANNUAL,
)
pgmcpp_asset_npc_cad = model.net_present_cost
external_economic_adjustment_cad = (
    POWERLINE_CAPITAL_COST_CAD
    + wind_fixed_om_npc_cad
    + bess_fixed_om_npc_cad
    - bess_residual_value_pv_cad
)
adjusted_npc_cad = (
    pgmcpp_asset_npc_cad + external_economic_adjustment_cad
)
served_energy_kwh = model.total_dispatch_kWh + model.total_discharge_kWh
if served_energy_kwh <= 0.0:
    raise RuntimeError("Cannot compute LCOE because served energy is zero")
recovery_factor = capital_recovery_factor(
    REAL_DISCOUNT_ANNUAL,
    economic_horizon_years,
)
adjusted_lcoe_cad_per_kwh = (
    economic_horizon_years
    * recovery_factor
    * adjusted_npc_cad
    / served_energy_kwh
)

# Replace the model-level economics so model.writeResults() and the compact
# summary report the corrected whole-project values. Asset-level result files
# retain the costs calculated internally by PGMcpp.
model.net_present_cost = adjusted_npc_cad
model.levellized_cost_of_energy_kWh = adjusted_lcoe_cad_per_kwh
print("Writing full PGMcpp result files...", flush=True)
model.writeResults(str(CASE_DIR))
print("Full result files written.", flush=True)

# =============================================================================
# SUMMARY
# =============================================================================
missed_load_vec_kw = model.controller.missed_load_vec_kW
missed_load_kwh = sum(
    p_kw * dt_hr
    for p_kw, dt_hr in zip(
        model.controller.missed_load_vec_kW,
        model.electrical_load.dt_vec_hrs,
    )
)
missed_load_peak_kw = max(missed_load_vec_kw)
missed_load_steps = sum(1 for p_kw in missed_load_vec_kw if p_kw > 0.0)
average_dt_hr = sum(model.electrical_load.dt_vec_hrs) / len(model.electrical_load.dt_vec_hrs)
missed_load_hours = missed_load_steps * average_dt_hr
renewable_dispatch_kwh = model.total_renewable_noncombustion_dispatch_kWh
combustion_dispatch_kwh = model.total_dispatch_kWh - renewable_dispatch_kwh
summary = {
    "case_name": CASE_NAME,
    "control_mode": CONTROL_MODE,
    "load_growth_annual": LOAD_GROWTH,
    "fuel_escalation_annual": FUEL_ESCALATION,
    "powerline_distance_km": POWERLINE_DISTANCE_KM,
    "initial_project_capex_CAD": (
        WIND_CAPITAL_COST_CAD
        + BESS_CAPITAL_COST_CAD
        + POWERLINE_CAPITAL_COST_CAD
    ),
    "pgmcpp_asset_npc_before_external_adjustments_CAD": pgmcpp_asset_npc_cad,
    "powerline_initial_capex_CAD": POWERLINE_CAPITAL_COST_CAD,
    "wind_fixed_om_annual_CAD_per_yr": WIND_FIXED_OM_ANNUAL_CAD,
    "wind_fixed_om_npc_CAD": wind_fixed_om_npc_cad,
    "bess_fixed_om_annual_CAD_per_yr": BESS_FIXED_OM_ANNUAL_CAD,
    "bess_fixed_om_npc_CAD": bess_fixed_om_npc_cad,
    "bess_terminal_remaining_life_fraction": bess_remaining_life_fraction,
    "bess_terminal_residual_value_CAD": bess_terminal_residual_value_cad,
    "bess_residual_value_present_value_CAD": bess_residual_value_pv_cad,
    "external_economic_adjustment_CAD": external_economic_adjustment_cad,
    "net_present_cost_CAD": model.net_present_cost,
    "lcoe_CAD_per_kWh": model.levellized_cost_of_energy_kWh,
    "total_fuel_consumed_L": model.total_fuel_consumed_L,
    "annual_avg_fuel_L_per_yr": model.total_fuel_consumed_L / model.electrical_load.n_years,
    "renewable_penetration": model.renewable_penetration,
    "total_dispatch_kWh": model.total_dispatch_kWh,
    "renewable_dispatch_kWh": renewable_dispatch_kwh,
    "combustion_dispatch_kWh": combustion_dispatch_kwh,
    "renewable_charge_kWh": model.total_renewable_noncombustion_charge_kWh,
    "missed_load_kWh": missed_load_kwh,
    "missed_load_peak_kW": missed_load_peak_kw,
    "missed_load_hours": missed_load_hours,
    "bess_replacements": bess_asset.n_replacements,
    "wind_replacements": 0,
    "bess_final_SOH": bess_asset.SOH,
    "bess_total_discharge_EFC": (bess_asset.total_discharge_kWh / BESS_ENERGY_KWH),
}
with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
    writer.writeheader()
    writer.writerow(summary)
print("-" * 72)
print(f"Summary CSV:         {SUMMARY_CSV}")
print(f"Missed load:         {missed_load_kwh:.3f} kWh")
print(f"Missed-load peak:    {missed_load_peak_kw:.3f} kW")
print(f"Missed-load hours:   {missed_load_hours:.3f} hr")
print("Wind replacements:   0")
print(f"BESS replacements:   {bess_asset.n_replacements}")
print(f"BESS residual PV:    {bess_residual_value_pv_cad:,.2f} CAD")
print(f"Corrected NPC:       {model.net_present_cost:,.2f} CAD")
print(f"Corrected LCOE:      {model.levellized_cost_of_energy_kWh:.6f} CAD/kWh")
