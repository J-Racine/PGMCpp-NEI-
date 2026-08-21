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

Run the Paulatuk variable-load, diesel-only baseline case.


Original software author: Anthony Truelove, MASc, P.Eng.
Project adaptation and modifications: Jonathan Racine, Northern Energy
Innovation, 2026.

Baseline definition:
    - Variable/nonlinear 20-year electrical-load profile
    - Existing diesel fleet only
    - No powerline cost or model component
    - No wind, solar, or other renewable generation
    - No battery energy storage system (BESS)

Last edited: 2026-08-21.
"""

import csv
import sys
from pathlib import Path


# =============================================================================
# PATHS
# =============================================================================

PROJECTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECTS_DIR.parent
BINDINGS_DIR = ROOT_DIR / "pybindings" / "precompiled_bindings"
LOAD_DIR = ROOT_DIR / "data" / "test" / "electrical_load"

LOAD_CSV = LOAD_DIR / "paulatuk_feeder_load_20yr_nonlinear_pgmcpp.csv"
RESULTS_DIR = PROJECTS_DIR / "results" / "paulatuk_variable_load_diesel_baseline"
SUMMARY_CSV = RESULTS_DIR / "summary.csv"

sys.path.insert(0, str(BINDINGS_DIR))

import PGMcpp  # noqa: E402 - binding path must be configured first


# =============================================================================
# BASELINE PARAMETERS
# =============================================================================

CASE_NAME = "psis_variable_load_diesel_baseline"
LOAD_GROWTH_CASE = "variable_nonlinear"
CONTROL_MODE_NAME = "PSIS"
CONTROL_MODE = PGMcpp.ControlMode.PSIS

# Existing Paulatuk diesel fleet; all units are treated as sunk assets.
DIESEL_CAPACITIES_KW = [250.0, 400.0, 412.0]
DIESEL_MINIMUM_LOAD_RATIO = 0.50
DIESEL_MINIMUM_RUNTIME_HR = 1.0
DIESEL_CYCLE_CHARGING_SETPOINT = 0.50

FIRM_DISPATCH_RATIO = 0.0
LOAD_RESERVE_RATIO = 0.10

FUEL_COST_CAD_PER_L = 2.58
FUEL_ESCALATION_ANNUAL = 0.0446
NOMINAL_INFLATION_ANNUAL = 0.0222
NOMINAL_DISCOUNT_ANNUAL = 0.05


def validate_inputs() -> None:
    """Fail early with a clear message when a required input is missing."""
    if not BINDINGS_DIR.exists():
        raise FileNotFoundError(f"PGMcpp binding directory not found: {BINDINGS_DIR}")
    if not LOAD_CSV.is_file():
        raise FileNotFoundError(f"Electrical-load CSV not found: {LOAD_CSV}")


def build_model():
    """Create the variable-load baseline with the existing diesel fleet only."""
    model_inputs = PGMcpp.ModelInputs()
    model_inputs.path_2_electrical_load_time_series = str(LOAD_CSV)
    model_inputs.control_mode = CONTROL_MODE
    model_inputs.firm_dispatch_ratio = FIRM_DISPATCH_RATIO
    model_inputs.load_reserve_ratio = LOAD_RESERVE_RATIO

    model = PGMcpp.Model(model_inputs)

    for capacity_kw in DIESEL_CAPACITIES_KW:
        diesel = PGMcpp.DieselInputs()
        production = diesel.combustion_inputs.production_inputs
        production.capacity_kW = capacity_kw
        production.is_sunk = True
        production.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
        production.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL

        diesel.combustion_inputs.fuel_mode = PGMcpp.FuelMode.FUEL_MODE_LINEAR
        diesel.combustion_inputs.nominal_fuel_escalation_annual = (
            FUEL_ESCALATION_ANNUAL
        )
        diesel.combustion_inputs.cycle_charging_setpoint = (
            DIESEL_CYCLE_CHARGING_SETPOINT
        )
        diesel.fuel_cost_L = FUEL_COST_CAD_PER_L
        diesel.minimum_load_ratio = DIESEL_MINIMUM_LOAD_RATIO
        diesel.minimum_runtime_hrs = DIESEL_MINIMUM_RUNTIME_HR
        model.addDiesel(diesel)

    return model


def calculate_missed_load(model):
    """Return missed energy, peak power, and duration."""
    missed_load_kw = model.controller.missed_load_vec_kW
    time_steps_hr = model.electrical_load.dt_vec_hrs

    missed_load_kwh = sum(
        power_kw * duration_hr
        for power_kw, duration_hr in zip(missed_load_kw, time_steps_hr)
    )
    missed_load_peak_kw = max(missed_load_kw, default=0.0)
    missed_load_hours = sum(
        duration_hr
        for power_kw, duration_hr in zip(missed_load_kw, time_steps_hr)
        if power_kw > 0.0
    )
    return missed_load_kwh, missed_load_peak_kw, missed_load_hours


def write_summary(model) -> dict:
    """Write a compact summary containing diesel-baseline metrics only."""
    missed_load_kwh, missed_load_peak_kw, missed_load_hours = (
        calculate_missed_load(model)
    )

    summary = {
        "case_name": CASE_NAME,
        "control_mode": CONTROL_MODE_NAME,
        "load_growth_case": LOAD_GROWTH_CASE,
        "fuel_escalation_annual": FUEL_ESCALATION_ANNUAL,
        "diesel_installed_capacity_kW": sum(DIESEL_CAPACITIES_KW),
        "net_present_cost_CAD": model.net_present_cost,
        "lcoe_CAD_per_kWh": model.levellized_cost_of_energy_kWh,
        "total_fuel_consumed_L": model.total_fuel_consumed_L,
        "annual_avg_fuel_L_per_yr": (
            model.total_fuel_consumed_L / model.electrical_load.n_years
        ),
        "total_dispatch_kWh": model.total_dispatch_kWh,
        "missed_load_kWh": missed_load_kwh,
        "missed_load_peak_kW": missed_load_peak_kw,
        "missed_load_hours": missed_load_hours,
    }

    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary))
        writer.writeheader()
        writer.writerow(summary)

    return summary


def main() -> None:
    """Validate inputs, run the diesel-only model, and save its results."""

    validate_inputs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Paulatuk variable-load diesel-only baseline")
    print("-" * 72)
    print(f"Case name:          {CASE_NAME}")
    print(f"Controller:         {CONTROL_MODE_NAME}")
    print(f"Load CSV:           {LOAD_CSV}")
    print(f"Diesel fleet:       {DIESEL_CAPACITIES_KW} kW")
    print("Renewables:         none")
    print("BESS:               none")
    print("Powerline:          none")
    print(f"Output folder:      {RESULTS_DIR}")
    print("-" * 72)

    model = build_model()
    print("Running PGMcpp...", flush=True)
    model.run()
    print("PGMcpp run complete.", flush=True)

    print("Writing full PGMcpp result files...", flush=True)
    model.writeResults(str(RESULTS_DIR))
    print("Full result files written.", flush=True)

    summary = write_summary(model)
    print("-" * 72)
    print(f"Summary CSV:        {SUMMARY_CSV}")
    print(f"Missed load:        {summary['missed_load_kWh']:.3f} kWh")
    print(f"Missed-load peak:   {summary['missed_load_peak_kW']:.3f} kW")
    print(f"Missed-load hours:  {summary['missed_load_hours']:.3f} hr")


if __name__ == "__main__":
    main()
