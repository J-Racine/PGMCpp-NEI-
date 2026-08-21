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

Optimize Paulatuk PGMcpp system sizes under the configured constraints.


    New users should edit only USER CONFIGURATION. Optimization can take many
    hours; first use a small ANNEALING_MAXITER to verify paths and outputs.

Last edited: 2026-08-21.
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import scipy.optimize as spo


# =============================================================================
# USER CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DATA_ROOT = REPO_ROOT / "data" / "test"
BINDINGS_DIR = REPO_ROOT / "pybindings"

LOAD_CSV = (
    DATA_ROOT
    / "electrical_load"
    / "paulatuk_feeder_load_20yr_nonlinear_pgmcpp.csv"
)

WIND_RESOURCE_CSV = (
    DATA_ROOT
    / "resources"
    / "wind_resource_20yr_pgmcpp_full_year_mps.csv"
)

SOLAR_RESOURCE_CSV = (
    DATA_ROOT
    / "resources"
    / "solar_resource_20yr_pgmcpp_full_year_mps.csv"
)

RESULTS_ROOT = SCRIPT_DIR / "results" / "paulatuk_optimization"

CONTROL_MODE_NAME = "PSIS"
FIRM_DISPATCH_RATIO = 0.0
LOAD_RESERVE_RATIO = 0.10

PAULATUK_DIESEL_CAPACITIES_KW = (250.0, 400.0, 412.0)
DIESEL_MINIMUM_LOAD_RATIO = 0.40
DIESEL_MINIMUM_RUNTIME_HOURS = 1.0
DIESEL_CYCLE_CHARGING_SETPOINT = 0.40
DIESEL_FUEL_COST_CAD_PER_L = 2.58
DIESEL_NOMINAL_FUEL_ESCALATION_ANNUAL = 0.0446
DIESEL_REPLACEMENT_RUNNING_HOURS = 90000.0
DIESEL_OPERATION_MAINTENANCE_COST_CAD_PER_KWH = 0.05

# Apply one common economic basis to every production and storage asset.
NOMINAL_INFLATION_ANNUAL = 0.0222
NOMINAL_DISCOUNT_ANNUAL = 0.05

# Paulatuk fixed-tilt PV assumptions. The detailed model is required for the
# location, array geometry, and ground albedo values below to affect output.
SOLAR_POWER_MODEL_NAME = "SOLAR_POWER_DETAILED"
SOLAR_DERATING = 0.85
SOLAR_FIRMNESS_FACTOR = 0.0
SOLAR_RESOURCE_START_JULIAN_DAY = 9131.5  # 2025-01-01 00:00 UTC, relative to J2000 noon
PAULATUK_LATITUDE_DEG = 69.35
PAULATUK_LONGITUDE_DEG = -124.07
SOLAR_PANEL_AZIMUTH_DEG = 180.0  # due south
SOLAR_PANEL_TILT_DEG = 70.0      # steep fixed tilt for low sun and snow shedding
SOLAR_ALBEDO_GROUND_REFLECTANCE = 0.60

WIND_DESIGN_SPEED_MS = 14.0
WIND_FIRMNESS_FACTOR = 0.0

BESS_INITIAL_SOC = 0.20
BESS_MINIMUM_SOC = 0.10
BESS_HYSTERESIS_SOC = 0.89
BESS_MAXIMUM_SOC = 0.90
BESS_CHARGING_EFFICIENCY = 0.97
BESS_DISCHARGING_EFFICIENCY = 0.97

# Objective: minimize NPC plus explicit fuel-use, diesel-runtime, and
# diesel-start penalties among candidates satisfying the reliability limits.
# The finite penalty avoids the inf/NaN behaviour caused by weights such as
# 1e999. The fuel term intentionally adds extra weight even though fuel cost is
# already included in NPC.
MISSED_LOAD_TOLERANCE_KWH = 0.1
MISSED_SPINNING_RESERVE_TOLERANCE_KWH = 0.1
MISSED_FIRM_DISPATCH_TOLERANCE_KWH = 0.1
FUEL_PENALTY_CAD_PER_L = 4.0
DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR = 100.0
DIESEL_START_PENALTY_CAD_PER_START = 1000.0
INFEASIBLE_BASE_PENALTY_CAD = 1e12
RELIABILITY_PENALTY_CAD_PER_KWH = 1e8

# Flag final candidates that install material renewable capacity but accept a
# negligible amount of renewable energy. This is diagnostic only: it does not
# alter the objective or reject the candidate.
RENEWABLE_DISPATCH_WARNING_CAPACITY_KW = 10.0
RENEWABLE_DISPATCH_WARNING_FRACTION = 1e-4

# Bounds apply only where a technology is optimized in a given case.
WIND_BOUNDS_KW = (0.0, 2000.0)
SOLAR_BOUNDS_KW = (0.0, 2000.0)
BESS_POWER_BOUNDS_KW = (0.0, 1500.0)
BESS_ENERGY_BOUNDS_KWH = (0.0, 6000.0)
ASSET_ZERO_TOLERANCE = 1.0

# Validation-stage search settings. Increase to 500 only after the renewable
# dispatch warning is clear and repeated seeds return comparable solutions.
ANNEALING_MAXITER = 100
RANDOM_SEED = 420
NO_LOCAL_SEARCH = True

USD_TO_CAD = 1.40
REMOTE_FACTOR = 1.99

# Planning-level installed costs. Base values are converted from USD to CAD and
# multiplied by the same northern remote-cost factor used in the report. The
# existing diesel plant is sunk, but its future genset replacements are not.
DIESEL_REPLACEMENT_CAPITAL_COST_CAD_PER_KW = (
    1200.0 * USD_TO_CAD * REMOTE_FACTOR
)
WIND_CAPITAL_COST_CAD_PER_KW = (
    2256.06 * REMOTE_FACTOR * USD_TO_CAD
)
BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH = (
    1659.39 * USD_TO_CAD * REMOTE_FACTOR
)
# Explicit inverter/power-conversion cost prevents BESS power from being free.
# Replace the base value below if the project estimate uses a different PCS cost.
BESS_POWER_CAPITAL_COST_CAD_PER_KW = (
    450.0 * USD_TO_CAD * REMOTE_FACTOR
)
SOLAR_CAPITAL_COST_CAD_PER_KW = (
    1432.01 * REMOTE_FACTOR * USD_TO_CAD
)

# PGMcpp accepts variable O&M in CAD/kWh rather than fixed CAD/kW-year. These
# planning allowances approximate fixed and variable servicing on a throughput
# basis and, critically, prevent the constructors from applying generic costs.
WIND_OPERATION_MAINTENANCE_COST_CAD_PER_KWH = 0.04
SOLAR_OPERATION_MAINTENANCE_COST_CAD_PER_KWH = 0.07
BESS_OPERATION_MAINTENANCE_COST_CAD_PER_KWH = 0.02
BESS_REPLACEMENT_SOH = 0.80
BESS_POWER_DEGRADATION_ENABLED = False


sys.path.insert(0, str(BINDINGS_DIR))

import PGMcpp  # noqa: E402  (must be imported after updating sys.path)


SIZING_KEYS = (
    "solar_capacity_kW",
    "wind_capacity_kW",
    "liion_power_capacity_kW",
    "liion_energy_capacity_kWh",
)


@dataclass(frozen=True)
class OptimizationCase:
    """Definition of the free and fixed sizing variables for one run."""

    name: str
    output_name: str
    variable_names: tuple[str, ...]
    bounds: tuple[tuple[float, float], ...]
    fixed_sizing: Mapping[str, float]


OPTIMIZATION_CASES = (
    OptimizationCase(
        name="Case 1: optimize wind + BESS",
        output_name="case_1_wind_bess",
        variable_names=(
            "wind_capacity_kW",
            "liion_power_capacity_kW",
            "liion_energy_capacity_kWh",
        ),
        bounds=(
            WIND_BOUNDS_KW,
            BESS_POWER_BOUNDS_KW,
            BESS_ENERGY_BOUNDS_KWH,
        ),
        fixed_sizing={"solar_capacity_kW": 0.0},
    ),
    OptimizationCase(
        name="Case 2: optimize wind + solar + BESS",
        output_name="case_2_wind_solar_bess",
        variable_names=(
            "solar_capacity_kW",
            "wind_capacity_kW",
            "liion_power_capacity_kW",
            "liion_energy_capacity_kWh",
        ),
        bounds=(
            SOLAR_BOUNDS_KW,
            WIND_BOUNDS_KW,
            BESS_POWER_BOUNDS_KW,
            BESS_ENERGY_BOUNDS_KWH,
        ),
        fixed_sizing={},
    ),
    OptimizationCase(
        name="Case 3: optimize solar with fixed wind + BESS",
        output_name="case_3_fixed_wind_bess_optimize_solar",
        variable_names=("solar_capacity_kW",),
        bounds=(SOLAR_BOUNDS_KW,),
        fixed_sizing={
            "wind_capacity_kW": 1000.0,
            "liion_power_capacity_kW": 1000.0,
            "liion_energy_capacity_kWh": 2000.0,
        },
    ),
)


candidate_count = 1


def validate_configuration() -> None:
    """Fail early if a configured input path is incorrect."""

    if not hasattr(PGMcpp.ControlMode, CONTROL_MODE_NAME):
        raise RuntimeError(
            f"The loaded PGMcpp bindings do not expose ControlMode.{CONTROL_MODE_NAME}. "
            "Rebuild the bindings from the PSIS-enabled NEI source."
        )
    if not hasattr(PGMcpp.SolarPowerProductionModel, SOLAR_POWER_MODEL_NAME):
        raise RuntimeError(
            "The loaded PGMcpp bindings do not expose the detailed solar model."
        )

    if not 0.0 <= FIRM_DISPATCH_RATIO <= 1.0:
        raise ValueError("FIRM_DISPATCH_RATIO must be within [0, 1].")
    if not 0.0 <= LOAD_RESERVE_RATIO <= 1.0:
        raise ValueError("LOAD_RESERVE_RATIO must be within [0, 1].")
    if not 0.0 <= DIESEL_MINIMUM_LOAD_RATIO <= 1.0:
        raise ValueError("DIESEL_MINIMUM_LOAD_RATIO must be within [0, 1].")
    if not (
        0.0 <= BESS_MINIMUM_SOC
        <= BESS_INITIAL_SOC
        <= BESS_HYSTERESIS_SOC
        <= BESS_MAXIMUM_SOC
        <= 1.0
    ):
        raise ValueError(
            "BESS SOC values must satisfy min <= initial <= hysteresis <= max."
        )
    if not (
        0.0 < BESS_CHARGING_EFFICIENCY <= 1.0
        and 0.0 < BESS_DISCHARGING_EFFICIENCY <= 1.0
    ):
        raise ValueError("BESS efficiencies must be within (0, 1].")
    if NOMINAL_INFLATION_ANNUAL <= -1.0:
        raise ValueError("NOMINAL_INFLATION_ANNUAL must be greater than -1.")
    if NOMINAL_DISCOUNT_ANNUAL <= -1.0:
        raise ValueError("NOMINAL_DISCOUNT_ANNUAL must be greater than -1.")
    if FUEL_PENALTY_CAD_PER_L < 0.0:
        raise ValueError("FUEL_PENALTY_CAD_PER_L must be nonnegative.")
    if DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR < 0.0:
        raise ValueError(
            "DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR must be nonnegative."
        )
    if DIESEL_START_PENALTY_CAD_PER_START < 0.0:
        raise ValueError("DIESEL_START_PENALTY_CAD_PER_START must be nonnegative.")
    if INFEASIBLE_BASE_PENALTY_CAD < 0.0:
        raise ValueError("INFEASIBLE_BASE_PENALTY_CAD must be nonnegative.")
    if RELIABILITY_PENALTY_CAD_PER_KWH < 0.0:
        raise ValueError("RELIABILITY_PENALTY_CAD_PER_KWH must be nonnegative.")
    if RENEWABLE_DISPATCH_WARNING_CAPACITY_KW < 0.0:
        raise ValueError(
            "RENEWABLE_DISPATCH_WARNING_CAPACITY_KW must be nonnegative."
        )
    if not 0.0 <= RENEWABLE_DISPATCH_WARNING_FRACTION <= 1.0:
        raise ValueError(
            "RENEWABLE_DISPATCH_WARNING_FRACTION must be within [0, 1]."
        )
    if ANNEALING_MAXITER <= 0:
        raise ValueError("ANNEALING_MAXITER must be positive.")
    economic_inputs = {
        "DIESEL_FUEL_COST_CAD_PER_L": DIESEL_FUEL_COST_CAD_PER_L,
        "DIESEL_REPLACEMENT_CAPITAL_COST_CAD_PER_KW": (
            DIESEL_REPLACEMENT_CAPITAL_COST_CAD_PER_KW
        ),
        "DIESEL_OPERATION_MAINTENANCE_COST_CAD_PER_KWH": (
            DIESEL_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "WIND_CAPITAL_COST_CAD_PER_KW": WIND_CAPITAL_COST_CAD_PER_KW,
        "WIND_OPERATION_MAINTENANCE_COST_CAD_PER_KWH": (
            WIND_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "SOLAR_CAPITAL_COST_CAD_PER_KW": SOLAR_CAPITAL_COST_CAD_PER_KW,
        "SOLAR_OPERATION_MAINTENANCE_COST_CAD_PER_KWH": (
            SOLAR_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "BESS_POWER_CAPITAL_COST_CAD_PER_KW": (
            BESS_POWER_CAPITAL_COST_CAD_PER_KW
        ),
        "BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH": (
            BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH
        ),
        "BESS_OPERATION_MAINTENANCE_COST_CAD_PER_KWH": (
            BESS_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
    }
    invalid_costs = [
        f"{name}={value}"
        for name, value in economic_inputs.items()
        if not np.isfinite(value) or value < 0.0
    ]
    if invalid_costs:
        raise ValueError(
            "Economic inputs must be finite and nonnegative: "
            + ", ".join(invalid_costs)
        )
    required_paths = {
        "PGMcpp bindings directory": BINDINGS_DIR,
        "Paulatuk electrical-load CSV": LOAD_CSV,
        "Paulatuk wind-resource CSV": WIND_RESOURCE_CSV,
        "Paulatuk solar-resource CSV": SOLAR_RESOURCE_CSV,
    }
    missing = [f"{label}: {path}" for label, path in required_paths.items() if not path.exists()]

    if missing:
        formatted = "\n  - ".join(missing)
        raise FileNotFoundError(
            "Update the paths in the USER CONFIGURATION section. Missing:\n"
            f"  - {formatted}"
        )

    with SOLAR_RESOURCE_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        solar_header = next(csv.reader(file), [])
    if "Solar GHI [kW/m2]" not in solar_header:
        raise ValueError(
            "The solar resource CSV must contain a 'Solar GHI [kW/m2]' column. "
            f"Found: {solar_header}"
        )


def build_model() -> tuple[PGMcpp.Model, dict[str, int]]:
    """Construct the Paulatuk model and load both renewable resources."""

    model_inputs = PGMcpp.ModelInputs()
    model_inputs.path_2_electrical_load_time_series = str(LOAD_CSV)
    model_inputs.control_mode = getattr(PGMcpp.ControlMode, CONTROL_MODE_NAME)
    model_inputs.firm_dispatch_ratio = FIRM_DISPATCH_RATIO
    model_inputs.load_reserve_ratio = LOAD_RESERVE_RATIO

    model = PGMcpp.Model(model_inputs)

    resource_keys = {"Solar": 0, "Wind": 1}

    model.addResource(
        PGMcpp.RenewableType.SOLAR,
        str(SOLAR_RESOURCE_CSV),
        resource_keys["Solar"],
    )
    model.addResource(
        PGMcpp.RenewableType.WIND,
        str(WIND_RESOURCE_CSV),
        resource_keys["Wind"],
    )

    return model, resource_keys


def expand_sizing(
    variable_values: Sequence[float],
    optimization_case: OptimizationCase,
) -> dict[str, float]:
    """Combine a case's optimized values with its fixed capacities."""

    if len(variable_values) != len(optimization_case.variable_names):
        raise ValueError("Optimization variable count does not match the case definition.")

    sizing = {key: 0.0 for key in SIZING_KEYS}
    sizing.update(optimization_case.fixed_sizing)
    sizing.update(
        {
            name: float(value)
            for name, value in zip(
                optimization_case.variable_names,
                variable_values,
                strict=True,
            )
        }
    )
    # Treat near-zero continuous optimizer values as an absent asset. Storage
    # requires both nonzero power and energy capacity; otherwise omit it.
    for key in SIZING_KEYS:
        if sizing[key] < ASSET_ZERO_TOLERANCE:
            sizing[key] = 0.0
    if (
        sizing["liion_power_capacity_kW"] == 0.0
        or sizing["liion_energy_capacity_kWh"] == 0.0
    ):
        sizing["liion_power_capacity_kW"] = 0.0
        sizing["liion_energy_capacity_kWh"] = 0.0

    return sizing


def get_candidate_capital_cost_cad(sizing: Mapping[str, float]) -> float:
    """Return installed candidate CAPEX already assigned inside PGMcpp."""

    return float(
        sizing["wind_capacity_kW"] * WIND_CAPITAL_COST_CAD_PER_KW
        + sizing["solar_capacity_kW"] * SOLAR_CAPITAL_COST_CAD_PER_KW
        + sizing["liion_power_capacity_kW"] * BESS_POWER_CAPITAL_COST_CAD_PER_KW
        + sizing["liion_energy_capacity_kWh"] * BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH
    )


def add_fixed_diesel_plant(model: PGMcpp.Model) -> None:
    """Add the existing 250/400/412 kW Paulatuk diesel fleet."""

    for capacity_kW in PAULATUK_DIESEL_CAPACITIES_KW:
        diesel_inputs = PGMcpp.DieselInputs()
        combustion_inputs = diesel_inputs.combustion_inputs
        production_inputs = combustion_inputs.production_inputs

        production_inputs.capacity_kW = capacity_kW
        # The existing plant has no initial candidate capital cost.
        production_inputs.is_sunk = True
        production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
        production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
        diesel_inputs.replace_running_hrs = DIESEL_REPLACEMENT_RUNNING_HOURS
        diesel_inputs.capital_cost = (
            capacity_kW * DIESEL_REPLACEMENT_CAPITAL_COST_CAD_PER_KW
        )
        diesel_inputs.operation_maintenance_cost_kWh = (
            DIESEL_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        )
        diesel_inputs.minimum_runtime_hrs = DIESEL_MINIMUM_RUNTIME_HOURS
        combustion_inputs.cycle_charging_setpoint = (
            DIESEL_CYCLE_CHARGING_SETPOINT
        )
        combustion_inputs.nominal_fuel_escalation_annual = (
            DIESEL_NOMINAL_FUEL_ESCALATION_ANNUAL
        )
        diesel_inputs.minimum_load_ratio = DIESEL_MINIMUM_LOAD_RATIO
        model.addDiesel(diesel_inputs)

        # fuel_cost_L is exposed on the constructed Combustion asset rather
        # than CombustionInputs in the current Python bindings.
        model.combustion_ptr_vec[-1].fuel_cost_L = (
            DIESEL_FUEL_COST_CAD_PER_L
        )


def add_candidate_assets(
    model: PGMcpp.Model,
    resource_keys: Mapping[str, int],
    sizing: Mapping[str, float],
) -> None:
    """Add renewable and storage assets for one candidate."""

    solar_capacity_kW = sizing["solar_capacity_kW"]
    wind_capacity_kW = sizing["wind_capacity_kW"]
    liion_power_capacity_kW = sizing["liion_power_capacity_kW"]
    liion_energy_capacity_kWh = sizing["liion_energy_capacity_kWh"]

    if solar_capacity_kW > 0.0:
        solar_inputs = PGMcpp.SolarInputs()
        production_inputs = solar_inputs.renewable_inputs.production_inputs
        production_inputs.capacity_kW = solar_capacity_kW
        production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
        production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
        solar_inputs.capital_cost = (
            solar_capacity_kW * SOLAR_CAPITAL_COST_CAD_PER_KW
        )
        solar_inputs.operation_maintenance_cost_kWh = (
            SOLAR_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        )
        solar_inputs.resource_key = resource_keys["Solar"]
        solar_inputs.firmness_factor = SOLAR_FIRMNESS_FACTOR
        solar_inputs.derating = SOLAR_DERATING
        solar_inputs.julian_day = SOLAR_RESOURCE_START_JULIAN_DAY
        solar_inputs.latitude_deg = PAULATUK_LATITUDE_DEG
        solar_inputs.longitude_deg = PAULATUK_LONGITUDE_DEG
        solar_inputs.panel_azimuth_deg = SOLAR_PANEL_AZIMUTH_DEG
        solar_inputs.panel_tilt_deg = SOLAR_PANEL_TILT_DEG
        solar_inputs.albedo_ground_reflectance = SOLAR_ALBEDO_GROUND_REFLECTANCE
        solar_inputs.power_model = getattr(
            PGMcpp.SolarPowerProductionModel,
            SOLAR_POWER_MODEL_NAME,
        )
        model.addSolar(solar_inputs)

    if wind_capacity_kW > 0.0:
        wind_inputs = PGMcpp.WindInputs()
        production_inputs = wind_inputs.renewable_inputs.production_inputs
        production_inputs.capacity_kW = wind_capacity_kW
        production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
        production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
        wind_inputs.capital_cost = (
            wind_capacity_kW * WIND_CAPITAL_COST_CAD_PER_KW
        )
        wind_inputs.operation_maintenance_cost_kWh = (
            WIND_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        )
        wind_inputs.resource_key = resource_keys["Wind"]
        wind_inputs.design_speed_ms = WIND_DESIGN_SPEED_MS
        wind_inputs.firmness_factor = WIND_FIRMNESS_FACTOR
        model.addWind(wind_inputs)

    if liion_power_capacity_kW > 0.0 and liion_energy_capacity_kWh > 0.0:
        liion_inputs = PGMcpp.LiIonInputs()
        storage_inputs = liion_inputs.storage_inputs
        storage_inputs.power_capacity_kW = liion_power_capacity_kW
        storage_inputs.energy_capacity_kWh = liion_energy_capacity_kWh
        storage_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
        storage_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL
        liion_inputs.capital_cost = (
            liion_power_capacity_kW * BESS_POWER_CAPITAL_COST_CAD_PER_KW
            + liion_energy_capacity_kWh
            * BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH
        )
        liion_inputs.operation_maintenance_cost_kWh = (
            BESS_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        )
        liion_inputs.init_SOC = BESS_INITIAL_SOC
        liion_inputs.min_SOC = BESS_MINIMUM_SOC
        liion_inputs.hysteresis_SOC = BESS_HYSTERESIS_SOC
        liion_inputs.max_SOC = BESS_MAXIMUM_SOC
        liion_inputs.charging_efficiency = BESS_CHARGING_EFFICIENCY
        liion_inputs.discharging_efficiency = BESS_DISCHARGING_EFFICIENCY
        liion_inputs.replace_SOH = BESS_REPLACEMENT_SOH
        liion_inputs.power_degradation_flag = BESS_POWER_DEGRADATION_ENABLED
        model.addLiIon(liion_inputs)


def get_total_missed_load_kwh(model: PGMcpp.Model) -> float:
    """Integrate missed power over the model time steps."""

    return float(
        np.dot(
            model.controller.missed_load_vec_kW,
            model.electrical_load.dt_vec_hrs,
        )
    )


def integrate_controller_shortfall_kwh(
    model: PGMcpp.Model,
    vector_name: str,
) -> float:
    """Integrate a controller shortfall vector over the model time steps."""

    if not hasattr(model.controller, vector_name):
        raise RuntimeError(
            f"The loaded PGMcpp bindings do not expose controller.{vector_name}. "
            "Rebuild the NEI bindings so the configured reliability constraint "
            "can be enforced."
        )
    return float(
        np.dot(
            getattr(model.controller, vector_name),
            model.electrical_load.dt_vec_hrs,
        )
    )


def get_reliability_metrics(model: PGMcpp.Model) -> dict[str, float]:
    """Return all load, reserve, and firm-dispatch shortfalls."""

    return {
        "missed_load_kWh": get_total_missed_load_kwh(model),
        "missed_spinning_reserve_kWh": integrate_controller_shortfall_kwh(
            model,
            "missed_spinning_reserve_vec_kW",
        ),
        "missed_firm_dispatch_kWh": integrate_controller_shortfall_kwh(
            model,
            "missed_firm_dispatch_vec_kW",
        ),
    }


def get_reliability_excess_kwh(metrics: Mapping[str, float]) -> float:
    """Return total shortfall above the configured tolerances."""

    return float(
        max(0.0, metrics["missed_load_kWh"] - MISSED_LOAD_TOLERANCE_KWH)
        + max(
            0.0,
            metrics["missed_spinning_reserve_kWh"]
            - MISSED_SPINNING_RESERVE_TOLERANCE_KWH,
        )
        + max(
            0.0,
            metrics["missed_firm_dispatch_kWh"]
            - MISSED_FIRM_DISPATCH_TOLERANCE_KWH,
        )
    )


def get_reliability_penalty_cad(reliability_excess_kWh: float) -> float:
    """Return zero when feasible, otherwise the finite reliability penalty.

    P_reliability = 0,                                      E_excess = 0
                  = P_base + c_reliability * E_excess,      E_excess > 0
    """

    if reliability_excess_kWh <= 0.0:
        return 0.0

    return float(
        INFEASIBLE_BASE_PENALTY_CAD
        + RELIABILITY_PENALTY_CAD_PER_KWH * reliability_excess_kWh
    )


def get_diesel_operating_metrics(model: PGMcpp.Model) -> dict[str, float]:
    """Return cumulative diesel generator-hours and individual generator starts."""

    dt_vec_hrs = np.asarray(
        model.electrical_load.dt_vec_hrs,
        dtype=float,
    )
    diesel_generator_hours = 0.0
    diesel_start_count = 0

    for diesel in model.combustion_ptr_vec:
        running = np.asarray(diesel.is_running_vec, dtype=bool)

        if running.size != dt_vec_hrs.size:
            raise RuntimeError(
                "Diesel running-state and timestep vectors have different lengths."
            )

        diesel_generator_hours += float(
            np.dot(running.astype(float), dt_vec_hrs)
        )

        if running.size > 0:
            # Treat a generator running in the first sample as a start at the
            # beginning of the modelling horizon.
            diesel_start_count += int(running[0])
            diesel_start_count += int(
                np.count_nonzero((~running[:-1]) & running[1:])
            )

    return {
        "diesel_generator_hours": diesel_generator_hours,
        "diesel_start_count": float(diesel_start_count),
    }


def get_renewable_energy_metrics(
    model: PGMcpp.Model,
    sizing: Mapping[str, float],
) -> dict[str, float | bool]:
    """Return accepted renewable energy relative to electrical-load demand.

    Renewable energy includes energy dispatched directly to the load and
    renewable energy sent to storage. Curtailed energy and storage discharge
    are excluded, so storage discharge is not double-counted.
    """

    renewable_to_load_kWh = float(
        sum(asset.total_dispatch_kWh for asset in model.renewable_ptr_vec)
    )
    renewable_to_bess_kWh = float(
        sum(asset.total_stored_kWh for asset in model.renewable_ptr_vec)
    )
    load_energy_kWh = float(
        np.dot(
            model.electrical_load.load_vec_kW,
            model.electrical_load.dt_vec_hrs,
        )
    )

    if load_energy_kWh <= 0.0:
        raise RuntimeError("Integrated electrical-load demand must be positive.")

    renewable_energy_fraction = (
        renewable_to_load_kWh + renewable_to_bess_kWh
    ) / load_energy_kWh
    installed_renewable_capacity_kW = (
        sizing["solar_capacity_kW"] + sizing["wind_capacity_kW"]
    )
    renewable_dispatch_suspect = bool(
        installed_renewable_capacity_kW
        >= RENEWABLE_DISPATCH_WARNING_CAPACITY_KW
        and renewable_energy_fraction < RENEWABLE_DISPATCH_WARNING_FRACTION
    )

    return {
        "load_energy_kWh": load_energy_kWh,
        "installed_renewable_capacity_kW": installed_renewable_capacity_kW,
        "renewable_to_load_kWh": renewable_to_load_kWh,
        "renewable_to_bess_kWh": renewable_to_bess_kWh,
        "renewable_energy_fraction": renewable_energy_fraction,
        "renewable_dispatch_suspect": renewable_dispatch_suspect,
    }


def objective_function(
    variable_values: np.ndarray,
    model: PGMcpp.Model,
    resource_keys: Mapping[str, int],
    optimization_case: OptimizationCase,
    case_number: int,
    total_cases: int,
) -> float:
    """Minimize NPC plus diesel-use penalties subject to reliability limits."""

    global candidate_count

    print(
        f"Case {case_number}/{total_cases} | candidate {candidate_count:,}",
        flush=True,
    )
    candidate_count += 1

    model.reset()

    sizing = expand_sizing(variable_values, optimization_case)
    add_fixed_diesel_plant(model)
    add_candidate_assets(model, resource_keys, sizing)
    model.run()

    pgmcpp_net_present_cost_CAD = float(model.net_present_cost)
    candidate_capital_cost_CAD = get_candidate_capital_cost_cad(sizing)
    # Candidate CAPEX is already embedded in model.net_present_cost through
    # each asset's capital_cost input, so it must not be added again here.
    reliability_metrics = get_reliability_metrics(model)
    reliability_excess_kWh = get_reliability_excess_kwh(reliability_metrics)
    diesel_operating_metrics = get_diesel_operating_metrics(model)
    total_fuel_consumed_L = float(model.total_fuel_consumed_L)

    if not np.all(
        np.isfinite(
            [
                pgmcpp_net_present_cost_CAD,
                candidate_capital_cost_CAD,
                *reliability_metrics.values(),
                *diesel_operating_metrics.values(),
                total_fuel_consumed_L,
            ]
        )
    ):
        return np.inf

    fuel_penalty_CAD = FUEL_PENALTY_CAD_PER_L * total_fuel_consumed_L
    diesel_runtime_penalty_CAD = (
        DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR
        * diesel_operating_metrics["diesel_generator_hours"]
    )
    diesel_start_penalty_CAD = (
        DIESEL_START_PENALTY_CAD_PER_START
        * diesel_operating_metrics["diesel_start_count"]
    )
    reliability_penalty_CAD = get_reliability_penalty_cad(
        reliability_excess_kWh
    )
    objective = (
        pgmcpp_net_present_cost_CAD
        + fuel_penalty_CAD
        + diesel_runtime_penalty_CAD
        + diesel_start_penalty_CAD
        + reliability_penalty_CAD
    )

    return objective


def run_case(
    model: PGMcpp.Model,
    resource_keys: Mapping[str, int],
    optimization_case: OptimizationCase,
    case_number: int,
    total_cases: int,
) -> dict[str, object]:
    """Run one optimization, write its model results, and return a summary."""

    global candidate_count
    candidate_count = 1

    start_time = time.time()
    result = spo.dual_annealing(
        objective_function,
        bounds=list(optimization_case.bounds),
        args=(
            model,
            resource_keys,
            optimization_case,
            case_number,
            total_cases,
        ),
        maxiter=ANNEALING_MAXITER,
        seed=RANDOM_SEED,
        no_local_search=NO_LOCAL_SEARCH,
    )
    elapsed_seconds = time.time() - start_time

    # Re-run the optimum so the model contains the best candidate when results
    # are written.
    best_sizing = expand_sizing(result.x, optimization_case)
    objective_value = objective_function(
        result.x,
        model,
        resource_keys,
        optimization_case,
        case_number,
        total_cases,
    )

    case_results_path = RESULTS_ROOT / optimization_case.output_name
    model.writeResults(str(case_results_path))

    pgmcpp_net_present_cost_CAD = float(model.net_present_cost)
    candidate_capital_cost_CAD = get_candidate_capital_cost_cad(best_sizing)
    reliability_metrics = get_reliability_metrics(model)
    reliability_excess_kWh = get_reliability_excess_kwh(reliability_metrics)
    diesel_operating_metrics = get_diesel_operating_metrics(model)
    renewable_metrics = get_renewable_energy_metrics(model, best_sizing)
    diesel_runtime_penalty_CAD = (
        DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR
        * diesel_operating_metrics["diesel_generator_hours"]
    )
    diesel_start_penalty_CAD = (
        DIESEL_START_PENALTY_CAD_PER_START
        * diesel_operating_metrics["diesel_start_count"]
    )
    reliability_penalty_CAD = get_reliability_penalty_cad(
        reliability_excess_kWh
    )
    optimizer_objective_CAD = float(result.fun)
    objective_rerun_difference_CAD = objective_value - optimizer_objective_CAD
    objective_rerun_relative_difference = (
        objective_rerun_difference_CAD
        / max(abs(optimizer_objective_CAD), 1.0)
    )

    if renewable_metrics["renewable_dispatch_suspect"]:
        print(
            "WARNING: "
            f"{optimization_case.output_name} installed "
            f"{renewable_metrics['installed_renewable_capacity_kW']:.3f} kW "
            "of renewables, but accepted renewable energy was only "
            f"{renewable_metrics['renewable_energy_fraction']:.6%} of load.",
            flush=True,
        )

    return {
        "case": optimization_case.output_name,
        "solar_capacity_kW": best_sizing["solar_capacity_kW"],
        "wind_capacity_kW": best_sizing["wind_capacity_kW"],
        "liion_power_capacity_kW": best_sizing["liion_power_capacity_kW"],
        "liion_energy_capacity_kWh": best_sizing["liion_energy_capacity_kWh"],
        "nominal_inflation_annual": NOMINAL_INFLATION_ANNUAL,
        "nominal_discount_annual": NOMINAL_DISCOUNT_ANNUAL,
        "diesel_fuel_cost_CAD_per_L": DIESEL_FUEL_COST_CAD_PER_L,
        "diesel_fuel_escalation_annual": (
            DIESEL_NOMINAL_FUEL_ESCALATION_ANNUAL
        ),
        "diesel_replacement_capital_cost_CAD_per_kW": (
            DIESEL_REPLACEMENT_CAPITAL_COST_CAD_PER_KW
        ),
        "diesel_om_cost_CAD_per_kWh": (
            DIESEL_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "wind_capital_cost_CAD_per_kW": WIND_CAPITAL_COST_CAD_PER_KW,
        "wind_om_cost_CAD_per_kWh": (
            WIND_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "solar_capital_cost_CAD_per_kW": SOLAR_CAPITAL_COST_CAD_PER_KW,
        "solar_om_cost_CAD_per_kWh": (
            SOLAR_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "bess_power_capital_cost_CAD_per_kW": (
            BESS_POWER_CAPITAL_COST_CAD_PER_KW
        ),
        "bess_energy_capital_cost_CAD_per_kWh": (
            BESS_ENERGY_CAPITAL_COST_CAD_PER_KWH
        ),
        "bess_om_cost_CAD_per_kWh": (
            BESS_OPERATION_MAINTENANCE_COST_CAD_PER_KWH
        ),
        "pgmcpp_net_present_cost_CAD": pgmcpp_net_present_cost_CAD,
        "candidate_capital_cost_CAD": candidate_capital_cost_CAD,

        "objective_net_present_cost_CAD": (
            pgmcpp_net_present_cost_CAD
        ),
        "fuel_penalty_CAD_per_L": FUEL_PENALTY_CAD_PER_L,
        "fuel_penalty_CAD": (
            FUEL_PENALTY_CAD_PER_L * float(model.total_fuel_consumed_L)
        ),
        "diesel_runtime_penalty_CAD_per_generator_hour": (
            DIESEL_RUNTIME_PENALTY_CAD_PER_GENERATOR_HOUR
        ),
        "diesel_start_penalty_CAD_per_start": (
            DIESEL_START_PENALTY_CAD_PER_START
        ),
        "diesel_generator_hours": diesel_operating_metrics[
            "diesel_generator_hours"
        ],
        "diesel_start_count": int(
            diesel_operating_metrics["diesel_start_count"]
        ),
        "diesel_runtime_penalty_CAD": diesel_runtime_penalty_CAD,
        "diesel_start_penalty_CAD": diesel_start_penalty_CAD,
        "total_missed_load_kWh": reliability_metrics["missed_load_kWh"],
        "total_missed_spinning_reserve_kWh": reliability_metrics[
            "missed_spinning_reserve_kWh"
        ],
        "total_missed_firm_dispatch_kWh": reliability_metrics[
            "missed_firm_dispatch_kWh"
        ],
        "reliability_excess_kWh": reliability_excess_kWh,
        "reliability_base_penalty_CAD": INFEASIBLE_BASE_PENALTY_CAD,
        "reliability_penalty_CAD_per_kWh": (
            RELIABILITY_PENALTY_CAD_PER_KWH
        ),
        "reliability_penalty_CAD": reliability_penalty_CAD,
        "reliability_feasible": reliability_excess_kWh <= 0.0,
        "load_energy_kWh": renewable_metrics["load_energy_kWh"],
        "installed_renewable_capacity_kW": renewable_metrics[
            "installed_renewable_capacity_kW"
        ],
        "renewable_to_load_kWh": renewable_metrics[
            "renewable_to_load_kWh"
        ],
        "renewable_to_bess_kWh": renewable_metrics[
            "renewable_to_bess_kWh"
        ],
        "renewable_energy_fraction": renewable_metrics[
            "renewable_energy_fraction"
        ],
        "renewable_dispatch_suspect": renewable_metrics[
            "renewable_dispatch_suspect"
        ],
        "all_constraints_feasible": reliability_excess_kWh <= 0.0,
        "total_fuel_consumed_L": float(model.total_fuel_consumed_L),
        "penalized_objective_CAD": objective_value,
        "optimizer_result_fun_CAD": optimizer_objective_CAD,
        "objective_rerun_difference_CAD": objective_rerun_difference_CAD,
        "objective_rerun_relative_difference": (
            objective_rerun_relative_difference
        ),
        "optimizer_success": bool(result.success),
        "optimizer_iterations": int(result.nit),
        "optimizer_max_iterations_configured": ANNEALING_MAXITER,
        "optimizer_local_search_enabled": not NO_LOCAL_SEARCH,
        "optimizer_random_seed": RANDOM_SEED,
        "iteration_limit_reached": "maximum number of iteration"
        in " ".join(map(str, np.atleast_1d(result.message))).lower(),
        "optimizer_message": " ".join(map(str, np.atleast_1d(result.message))),
        "function_evaluations": int(result.nfev),
        "runtime_seconds": elapsed_seconds,
        "results_path": str(case_results_path),
    }


def write_master_summary(case_summaries: Sequence[Mapping[str, object]]) -> Path:
    """Write one comparison row per optimization case."""

    summary_path = RESULTS_ROOT / "optimization_case_summary.csv"
    fieldnames = list(case_summaries[0].keys())

    with summary_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(case_summaries)

    return summary_path


def run_case_worker(case_index: int) -> dict[str, object]:
    """Build an independent model and run one optimization case."""

    optimization_case = OPTIMIZATION_CASES[case_index]
    total_cases = len(OPTIMIZATION_CASES)
    model, resource_keys = build_model()

    return run_case(
        model=model,
        resource_keys=resource_keys,
        optimization_case=optimization_case,
        case_number=case_index + 1,
        total_cases=total_cases,
    )


def main() -> None:
    """Validate the study, run every optimization case, and write one master CSV."""

    validate_configuration()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)

    total_cases = len(OPTIMIZATION_CASES)
    print(f"Running {total_cases} optimization cases in parallel...")

    with ProcessPoolExecutor(max_workers=total_cases) as executor:
        summaries = list(
            executor.map(
                run_case_worker,
                range(total_cases),
            )
        )

    summary_path = write_master_summary(summaries)
    total_function_evaluations = sum(
        int(summary["function_evaluations"])
        for summary in summaries
    )
    total_simulations = total_function_evaluations + total_cases

    print()
    print("Optimization complete.")
    print(f"Total PGMcpp simulations: {total_simulations:,}")
    print(f"Master summary: {summary_path}")


if __name__ == "__main__":
    main()
