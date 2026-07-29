r"""
Run ONE Paulatuk PGMcpp simulation.

Copy this file into:
    C:\Users\jracine\Desktop\PGMcpp_NEI_version\projects

Run:
    python run_paulatuk_one.py

Edit only the CASE SELECTION block unless changing system assumptions.
"""

from pathlib import Path
import csv
import sys


# =============================================================================
# CASE SELECTION
# =============================================================================
# Available load-growth cases:       0.03, 0.08,100
# Available path lengths       2.8431 , 5.2333

LOAD_GROWTH = 100
FUEL_ESCALATION = 0.0446
POWERLINE_DISTANCE_KM = 5.2333


# =============================================================================
# PATHS
# =============================================================================

PROJECTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECTS_DIR.parent

BINDINGS_DIR = ROOT_DIR / "pybindings" / "precompiled_bindings"
LOAD_DIR = ROOT_DIR / "data" / "test" / "electrical_load"
RESOURCE_DIR = ROOT_DIR / "data" / "test" / "resources"
RESULTS_DIR = PROJECTS_DIR / "results" / "paulatuk_single_case"

LOAD_FILES = {
    0.03: LOAD_DIR / "paulatuk_load_20yr_growth_3pct_pgmcpp.csv",
    0.08: LOAD_DIR / "paulatuk_load_20yr_growth_8pct_pgmcpp.csv",
    100: LOAD_DIR / "paulatuk_feeder_load_20yr_nonlinear_pgmcpp.csv"
}

LOAD_CSV = LOAD_FILES[LOAD_GROWTH]
WIND_RESOURCE_CSV = RESOURCE_DIR / "wind_resource_20yr_pgmcpp_full_year_mps.csv"

sys.path.insert(0, str(BINDINGS_DIR))
import PGMcpp

# =============================================================================
# SYSTEM PARAMETERS
# =============================================================================

DIESEL_CAPACITIES_KW = [250.0, 400.0, 412.0]
DIESEL_MINIMUM_LOAD_RATIO = 0.20

WIND_CAPACITY_KW = 1000.0
WIND_DESIGN_SPEED_MS = 14.0
WIND_FIRMNESS_FACTOR = 0.0

BESS_POWER_KW = 1000.0
BESS_ENERGY_KWH = 2000.0

FIRM_DISPATCH_RATIO = 0.0
LOAD_RESERVE_RATIO = 0.10

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
    (2256.06 * WIND_CAPACITY_KW * REMOTE_FACTOR * USD_TO_CAD) + POWERLINE_COST_CAD_PER_KM * POWERLINE_DISTANCE_KM
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

CASE_NAME = f"growth_{int(LOAD_GROWTH * 100):02d}_PATH_{int(POWERLINE_DISTANCE_KM):02d}"
CASE_DIR = RESULTS_DIR / CASE_NAME
CASE_DIR.mkdir(parents=True, exist_ok=True)

print("Paulatuk PGMcpp single-case run")
print("-" * 72)
print(f"Case name:          {CASE_NAME}")
print(f"Load growth:        {LOAD_GROWTH:.0%}/yr")
print(f"Path length:        {POWERLINE_DISTANCE_KM:.0f} km")
print(f"Fuel escalation:    {FUEL_ESCALATION:.0%}/yr")
print(f"Load CSV:           {LOAD_CSV}")
print(f"Wind resource CSV:  {WIND_RESOURCE_CSV}")
print(f"Output folder:      {CASE_DIR}")
print(f"Wind O&M:           {WIND_OM_COST_CAD_PER_KWH:.6f} CAD/kWh")
print(f"BESS O&M:           {BESS_OM_COST_CAD_PER_KWH:.6f} CAD/kWh")
print("-" * 72)


# =============================================================================
# BUILD MODEL
# =============================================================================

model_inputs = PGMcpp.ModelInputs()
model_inputs.path_2_electrical_load_time_series = str(LOAD_CSV)
model_inputs.control_mode = PGMcpp.ControlMode.LOAD_FOLLOWING
model_inputs.firm_dispatch_ratio = FIRM_DISPATCH_RATIO
model_inputs.load_reserve_ratio = LOAD_RESERVE_RATIO

model = PGMcpp.Model(model_inputs)

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

    diesel.fuel_cost_L = FUEL_COST_CAD_PER_L
    diesel.minimum_load_ratio = DIESEL_MINIMUM_LOAD_RATIO

    model.addDiesel(diesel)


# =============================================================================
# WIND
# =============================================================================

wind = PGMcpp.WindInputs()

wind.renewable_inputs.production_inputs.capacity_kW = WIND_CAPACITY_KW
wind.renewable_inputs.production_inputs.is_sunk = False
wind.renewable_inputs.production_inputs.nominal_inflation_annual = NOMINAL_INFLATION_ANNUAL
wind.renewable_inputs.production_inputs.nominal_discount_annual = NOMINAL_DISCOUNT_ANNUAL

wind.resource_key = wind_resource_key
wind.firmness_factor = WIND_FIRMNESS_FACTOR
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

bess.power_degradation_flag = True
bess.init_SOC = 0.50
bess.min_SOC = 0.15
bess.hysteresis_SOC = 0.50
bess.max_SOC = 0.90
bess.charging_efficiency = 0.90
bess.discharging_efficiency = 0.90

bess.capital_cost = BESS_CAPITAL_COST_CAD
bess.operation_maintenance_cost_kWh = BESS_OM_COST_CAD_PER_KWH

model.addLiIon(bess)


# =============================================================================
# RUN
# =============================================================================

print("Running PGMcpp...", flush=True)

model.run()

print("PGMcpp run complete.", flush=True)

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
    "load_growth_annual": LOAD_GROWTH,
    "fuel_escalation_annual": FUEL_ESCALATION,
    "fuel_cost_CAD_per_L": FUEL_COST_CAD_PER_L,
    "nominal_inflation_annual": NOMINAL_INFLATION_ANNUAL,
    "nominal_discount_annual": NOMINAL_DISCOUNT_ANNUAL,
    "real_discount_annual": REAL_DISCOUNT_ANNUAL,
    "wind_capacity_kW": WIND_CAPACITY_KW,
    "bess_power_kW": BESS_POWER_KW,
    "bess_energy_kWh": BESS_ENERGY_KWH,
    "wind_capital_cost_CAD": WIND_CAPITAL_COST_CAD,
    "wind_om_cost_CAD_per_kWh": WIND_OM_COST_CAD_PER_KWH,
    "bess_capital_cost_CAD": BESS_CAPITAL_COST_CAD,
    "bess_om_cost_CAD_per_kWh": BESS_OM_COST_CAD_PER_KWH,
    "net_present_cost_CAD": model.net_present_cost,
    "lcoe_CAD_per_kWh": model.levellized_cost_of_energy_kWh,
    "total_fuel_consumed_L": model.total_fuel_consumed_L,
    "annual_avg_fuel_L_per_yr": model.total_fuel_consumed_L / model.electrical_load.n_years,
    "total_CO2_kg": model.total_emissions.CO2_kg,
    "annual_avg_CO2_kg_per_yr": model.total_emissions.CO2_kg / model.electrical_load.n_years,
    "renewable_penetration": model.renewable_penetration,
    "total_dispatch_kWh": model.total_dispatch_kWh,
    "renewable_dispatch_kWh": renewable_dispatch_kwh,
    "combustion_dispatch_kWh": combustion_dispatch_kwh,
    "renewable_charge_kWh": model.total_renewable_noncombustion_charge_kWh,
    "combustion_charge_kWh": model.total_combustion_charge_kWh,
    "storage_charge_kWh": (model.total_renewable_noncombustion_charge_kWh + model.total_combustion_charge_kWh),
    "storage_discharge_kWh": model.total_discharge_kWh,
    "missed_load_kWh": missed_load_kwh,
    "missed_load_peak_kW": missed_load_peak_kw,
    "missed_load_hours": missed_load_hours,
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