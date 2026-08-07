from pathlib import Path
import csv
import itertools
import os
import subprocess
import sys


# =============================================================================
# BATCH CASE SELECTION
# =============================================================================
LOAD_GROWTH_CASES = [0.03, 0.08, 0.666]
FUEL_ESCALATION_CASES = [0.0446]
POWERLINE_DISTANCE_CASES_KM = [2.8431, 5.2333, 3.780]
CONTROL_MODES_TO_RUN = ["PSIS"]


def number_tag(value, decimal_places):
    """Return a filesystem-safe fixed-decimal number."""
    return f"{value:.{decimal_places}f}".replace("-", "m").replace(".", "p")


def make_case_name(control_mode, load_growth, fuel_escalation, distance_km):
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
    batch_results_dir = (
        script_path.parent / "results" / "paulatuk_all_cases"
    )
    batch_results_dir.mkdir(parents=True, exist_ok=True)
    completed_summaries = []
    failed_cases = []

    print(f"Running {len(case_matrix)} Paulatuk cases sequentially.")

    for case_number, (
        load_growth,
        fuel_escalation,
        distance_km,
        control_mode,
    ) in enumerate(case_matrix, start=1):
        case_name = make_case_name(
            control_mode,
            load_growth,
            fuel_escalation,
            distance_km,
        )
        print("=" * 72)
        print(f"Batch case {case_number}/{len(case_matrix)}: {case_name}")
        print("=" * 72, flush=True)

        child_environment = os.environ.copy()
        child_environment.update(
            {
                "PAULATUK_BATCH_CHILD": "1",
                "PAULATUK_LOAD_GROWTH": str(load_growth),
                "PAULATUK_FUEL_ESCALATION": str(fuel_escalation),
                "PAULATUK_LINE_DISTANCE_KM": str(distance_km),
                "PAULATUK_CONTROL_MODE": control_mode,
            }
        )
        try:
            subprocess.run(
                [sys.executable, str(script_path)],
                env=child_environment,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            failed_cases.append(
                {
                    "case_name": case_name,
                    "return_code": error.returncode,
                }
            )
            print(
                f"Case failed with return code {error.returncode}: "
                f"{case_name}",
                file=sys.stderr,
            )
            continue

        completed_summaries.append(
            batch_results_dir / case_name / "summary.csv"
        )

    master_rows = []
    for summary_path in completed_summaries:
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
WIND_NORMALIZED_CSV = Path(r"C:\Users\jracine\Desktop\PGMcpp_NEI_version\data\test\normalized_production\ie0124_paulatuk_wind_normalized_20yr_1min.csv")

sys.path.insert(0, str(BINDINGS_DIR))
import PGMcpp

# =============================================================================
# SYSTEM PARAMETERS
# =============================================================================

DIESEL_CAPACITIES_KW = [250.0, 400.0, 412.0]
DIESEL_MINIMUM_LOAD_RATIO = 0.50

WIND_CAPACITY_KW = 1000.0
WIND_DESIGN_SPEED_MS = 14.0
WIND_FIRMNESS_FACTOR = 0.0

BESS_POWER_KW = 1000.0
BESS_ENERGY_KWH = 2000.0

FIRM_DISPATCH_RATIO = 0.0
LOAD_RESERVE_RATIO = 0.10

# PSIS controller settings. These are ignored in LOAD_FOLLOWING mode.
PSIS_DIESEL_ON_SOC = 0.10
PSIS_DIESEL_OFF_SOC = 0.89
PSIS_WIND_SHUTDOWN_MARGIN_RATIO = 0.00
PSIS_WIND_SHUTDOWN_PERSISTENCE_HR = 1/60

DIESEL_MINIMUM_RUNTIME_HR = 1.0
DIESEL_CYCLE_CHARGING_SETPOINT = 0.50

FUEL_COST_CAD_PER_L = 2.58

NOMINAL_INFLATION_ANNUAL = 0.0222
NOMINAL_DISCOUNT_ANNUAL = 0.05
REAL_DISCOUNT_ANNUAL = (
    (1.0 + NOMINAL_DISCOUNT_ANNUAL) / (1.0 + NOMINAL_INFLATION_ANNUAL) - 1.0
)


# =============================================================================
# COSTS
# =============================================================================

USD_TO_CAD = 1.40
REMOTE_FACTOR = 1.99
CONTINGENCY_FACTOR = 1.30
POWERLINE_COST_CAD_PER_KM = 1_500_000

WIND_CAPITAL_COST_CAD = (
    (2256.06 * WIND_CAPACITY_KW * REMOTE_FACTOR * USD_TO_CAD) + POWERLINE_COST_CAD_PER_KM * POWERLINE_DISTANCE_KM * CONTINGENCY_FACTOR
)

BESS_CAPITAL_COST_CAD = (
    1659.39 * BESS_ENERGY_KWH * USD_TO_CAD * REMOTE_FACTOR
)

# Fixed O&M source values [USD/kW-yr]
WIND_FIXED_OM_USD_PER_KW_YR = 38.627
BESS_FIXED_OM_USD_PER_KW_YR = 37.522

# Actual 20-year baseline outputs used to convert fixed O&M into PGMcpp variable O&M.
BASELINE_YEARS = 20.0
BASELINE_WIND_DISPATCH_KWH = 1.6238e7
BASELINE_WIND_CHARGE_KWH = 3.04888e6
BASELINE_BESS_DISCHARGE_KWH = 2.47136e6

WIND_OM_COST_CAD_PER_KWH = (
    WIND_FIXED_OM_USD_PER_KW_YR
    * USD_TO_CAD
    * REMOTE_FACTOR
    * WIND_CAPACITY_KW
    * BASELINE_YEARS
) / (BASELINE_WIND_DISPATCH_KWH + BASELINE_WIND_CHARGE_KWH)

BESS_OM_COST_CAD_PER_KWH = (
    BESS_FIXED_OM_USD_PER_KW_YR
    * USD_TO_CAD
    * REMOTE_FACTOR
    * BESS_POWER_KW
    * BASELINE_YEARS
) / BASELINE_BESS_DISCHARGE_KWH


# =============================================================================
# CASE SETUP
# =============================================================================

CASE_NAME = make_case_name(
    CONTROL_MODE,
    LOAD_GROWTH,
    FUEL_ESCALATION,
    POWERLINE_DISTANCE_KM,
)
CASE_DIR = RESULTS_DIR / CASE_NAME
CASE_DIR.mkdir(parents=True, exist_ok=True)

print("Paulatuk PGMcpp batch case")
print("-" * 72)
print(f"Case name:          {CASE_NAME}")
print(f"Controller:         {CONTROL_MODE}")
print(f"Load growth:        {LOAD_GROWTH:.0%}/yr")
print(f"Path length:        {POWERLINE_DISTANCE_KM:.0f} km")
print(f"Fuel escalation:    {FUEL_ESCALATION:.0%}/yr")
print(f"Load CSV:           {LOAD_CSV}")
print(f"Wind resource CSV:  {WIND_RESOURCE_CSV}")
print(f"Wind normalized CSV:{WIND_NORMALIZED_CSV}")
print(f"Output folder:      {CASE_DIR}")
print(f"Wind O&M:           {WIND_OM_COST_CAD_PER_KWH:.6f} CAD/kWh")
print(f"BESS O&M:           {BESS_OM_COST_CAD_PER_KWH:.6f} CAD/kWh")
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
    model.controller.psis_wind_shutdown_margin_ratio = (
        PSIS_WIND_SHUTDOWN_MARGIN_RATIO
    )
    model.controller.psis_wind_shutdown_persistence_hrs = (
        PSIS_WIND_SHUTDOWN_PERSISTENCE_HR
    )

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
    diesel.combustion_inputs.cycle_charging_setpoint = (
        DIESEL_CYCLE_CHARGING_SETPOINT
    )

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
wind.renewable_inputs.production_inputs.path_2_normalized_production_time_series = (
    str(WIND_NORMALIZED_CSV)
)

wind.resource_key = wind_resource_key
wind.firmness_factor = WIND_FIRMNESS_FACTOR
# When a normalized production time series is supplied above, PGMcpp uses it
# directly and bypasses this cubic wind-speed production model.
wind.design_speed_ms = WIND_DESIGN_SPEED_MS
wind.power_model = PGMcpp.WindPowerProductionModel.WIND_POWER_CUBIC

wind.capital_cost = WIND_CAPITAL_COST_CAD
wind.operation_maintenance_cost_kWh = WIND_OM_COST_CAD_PER_KWH

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
bess.init_SOC = 0.20
bess.min_SOC = 0.10
bess.hysteresis_SOC = 0.89
bess.max_SOC = 0.90
bess.charging_efficiency = 0.97
bess.discharging_efficiency = 0.97

bess.capital_cost = BESS_CAPITAL_COST_CAD
bess.operation_maintenance_cost_kWh = BESS_OM_COST_CAD_PER_KWH

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

print("Writing full PGMcpp time-series result files...", flush=True)
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
    "bess_final_SOH": bess_asset.SOH,
    "bess_total_discharge_EFC": (
        bess_asset.total_discharge_kWh / BESS_ENERGY_KWH
    ),
}

summary_csv = CASE_DIR / "summary.csv"
with summary_csv.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
    writer.writeheader()
    writer.writerow(summary)

print("-" * 72)
print(f"Done. Results folder: {CASE_DIR}")
print(f"Summary CSV:         {summary_csv}")
print(f"Missed load:         {missed_load_kwh:.3f} kWh")
print(f"Missed-load peak:    {missed_load_peak_kw:.3f} kW")
print(f"Missed-load hours:   {missed_load_hours:.3f} hr")