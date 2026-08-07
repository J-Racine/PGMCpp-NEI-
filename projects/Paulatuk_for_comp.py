from pathlib import Path
import csv
import sys


# =============================================================================
# FILE LOCATIONS
# These paths assume this script is inside the PGMcpp "projects" folder.
# =============================================================================

PROJECTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECTS_DIR.parent

PGMCPP_BINDINGS = str(ROOT_DIR / "pybindings")
ELECTRICAL_LOAD_CSV = str(
    ROOT_DIR
    / "data"
    / "test"
    / "electrical_load"
    / "paulatuk_feeder_load_test.csv"
)
WIND_PRODUCTION_CSV = (
    r"C:\Users\jracine\Desktop\PGMcpp_NEI_version\data\test"
    r"\normalized_production\ie0124_paulatuk_wind_46m_1min_2026_06.csv"
)

OUTPUT_LOCATION = str(
    PROJECTS_DIR / "results" / "paulatuk_single_case"
)
OUTPUT_NAME = "paulatuk comp"


# =============================================================================
# MODEL SETTINGS
# =============================================================================

# Controller
FIRM_DISPATCH_RATIO = 0.00 # Fraction of load that must be met by "firm" sources
LOAD_RESERVE_RATIO = 0.10 # Additional fraction of load that must be meetable by sources

PSIS_DIESEL_ON_SOC = 0.10 # Minimum state of charge threshold to turn on diesel generators
PSIS_DIESEL_OFF_SOC = 0.89 # Maximum state of charge threshold to turn off diesel generators
PSIS_WIND_SHUTDOWN_MARGIN_RATIO = 0.0 # Additional margin for shutting down wind turbines
PSIS_WIND_SHUTDOWN_PERSISTENCE_HR = (1/60) # Minimum time that the wind turbine must cover the load before diesel generators are turned off

# Diesel generators
DIESEL_CAPACITIES_KW = [250.0, 400.0, 412.0] # Capacities of the diesel generators in kW
DIESEL_MINIMUM_LOAD_RATIO = 0.20   # Minimum load ratio for diesel generators (not used in PSIS mode)
DIESEL_MINIMUM_RUNTIME_HR = 1.0 # Minimum runtime for diesel generators in hours
DIESEL_REPLACEMENT_RUNNING_HR = 30_000.0 # Running hours after which diesel generators are replaced
DIESEL_CYCLE_CHARGING_SETPOINT = 0.50 # Diesel minimum load at which the diesel generators will start charging the battery (not used in PSIS mode)

# Diesel emissions [kg/L fuel]
DIESEL_CO2_KG_PER_L = 2.7000 # CO2 emissions intensity for diesel fuel
DIESEL_CO_KG_PER_L = 0.0178 # CO emissions intensity for diesel fuel
DIESEL_NOX_KG_PER_L = 0.0014 # NOx emissions intensity for diesel fuel
DIESEL_SOX_KG_PER_L = 0.0042 # SOx emissions intensity for diesel fuel
DIESEL_CH4_KG_PER_L = 0.0007 # CH4 emissions intensity for diesel fuel
DIESEL_PM_KG_PER_L = 0.0001 # PM emissions intensity for diesel fuel

# Wind turbine
WIND_CAPACITY_KW = 1000.0 # Capacity of the wind turbine in kW
WIND_REPLACEMENT_RUNNING_HR = 90_000.0 # Running hours after which the wind turbine is replaced
WIND_FIRMNESS_FACTOR = 0.00 # Fraction of wind production that is considered "firm" (not used in PSIS mode)
WIND_DESIGN_SPEED_M_PER_S = 14.0 # Design wind speed for the wind turbine in m/s (not used with nominal production time series)

# Li-ion battery
BESS_POWER_KW = 1000.0 # Power capacity of the battery in kW
BESS_ENERGY_KWH = 2000.0  # Energy capacity of the battery in kWh
BESS_INITIAL_SOC = 0.20 # Initial state of charge of the battery (fraction of energy capacity)
BESS_MINIMUM_SOC = 0.10 # Minimum state of charge for the battery (fraction of energy capacity)
BESS_HYSTERESIS_SOC = 0.89 # Hysteresis state of charge for the battery (when it gets the greenlight to discharge) (fraction of energy capacity)
BESS_MAXIMUM_SOC = 0.90 # Maximum state of charge for the battery (fraction of energy capacity)
BESS_CHARGING_EFFICIENCY = 0.97 # Charging efficiency of the battery (fraction)
BESS_DISCHARGING_EFFICIENCY = 0.97 # Discharging efficiency of the battery (fraction)
BESS_REPLACEMENT_SOH = 0.80 # State of health at which the battery is replaced (fraction)
BESS_MODEL_POWER_DEGRADATION = False # Flag to enable power degradation model for the battery (True/False)


# =============================================================================
# IMPORT PGMCPP
# =============================================================================

sys.path.insert(0, PGMCPP_BINDINGS)
import PGMcpp


# =============================================================================
# 1. CREATE THE MODEL
# =============================================================================

model_inputs = PGMcpp.ModelInputs()
model_inputs.path_2_electrical_load_time_series = ELECTRICAL_LOAD_CSV
model_inputs.control_mode = PGMcpp.ControlMode.PSIS
model_inputs.firm_dispatch_ratio = FIRM_DISPATCH_RATIO
model_inputs.load_reserve_ratio = LOAD_RESERVE_RATIO

model = PGMcpp.Model(model_inputs)

model.controller.psis_diesel_on_soc = PSIS_DIESEL_ON_SOC
model.controller.psis_diesel_off_soc = PSIS_DIESEL_OFF_SOC
model.controller.psis_wind_shutdown_margin_ratio = (
    PSIS_WIND_SHUTDOWN_MARGIN_RATIO
)
model.controller.psis_wind_shutdown_persistence_hrs = (
    PSIS_WIND_SHUTDOWN_PERSISTENCE_HR
)


# =============================================================================
# 2. ADD THE DIESEL GENERATORS
# =============================================================================

for capacity_kw in DIESEL_CAPACITIES_KW:
    diesel_inputs = PGMcpp.DieselInputs()

    diesel_inputs.combustion_inputs.production_inputs.print_flag = True
    diesel_inputs.combustion_inputs.production_inputs.capacity_kW = capacity_kw
    diesel_inputs.combustion_inputs.production_inputs.is_sunk = True
    diesel_inputs.combustion_inputs.production_inputs.nominal_inflation_annual = 0.0
    diesel_inputs.combustion_inputs.production_inputs.nominal_discount_annual = 0.0

    diesel_inputs.combustion_inputs.fuel_mode = (
        PGMcpp.FuelMode.FUEL_MODE_LINEAR
    )
    diesel_inputs.combustion_inputs.nominal_fuel_escalation_annual = 0.0
    diesel_inputs.combustion_inputs.cycle_charging_setpoint = (
        DIESEL_CYCLE_CHARGING_SETPOINT
    )

    diesel_inputs.replace_running_hrs = DIESEL_REPLACEMENT_RUNNING_HR
    diesel_inputs.minimum_load_ratio = DIESEL_MINIMUM_LOAD_RATIO
    diesel_inputs.minimum_runtime_hrs = DIESEL_MINIMUM_RUNTIME_HR
    diesel_inputs.linear_fuel_slope_LkWh = -1.0
    diesel_inputs.linear_fuel_intercept_LkWh = -1.0

    diesel_inputs.capital_cost = 0.0
    diesel_inputs.operation_maintenance_cost_kWh = 0.0
    diesel_inputs.fuel_cost_L = 0.0

    diesel_inputs.CO2_emissions_intensity_kgL = DIESEL_CO2_KG_PER_L
    diesel_inputs.CO_emissions_intensity_kgL = DIESEL_CO_KG_PER_L
    diesel_inputs.NOx_emissions_intensity_kgL = DIESEL_NOX_KG_PER_L
    diesel_inputs.SOx_emissions_intensity_kgL = DIESEL_SOX_KG_PER_L
    diesel_inputs.CH4_emissions_intensity_kgL = DIESEL_CH4_KG_PER_L
    diesel_inputs.PM_emissions_intensity_kgL = DIESEL_PM_KG_PER_L

    model.addDiesel(diesel_inputs)


# =============================================================================
# 3. ADD THE WIND TURBINE
# =============================================================================

wind_inputs = PGMcpp.WindInputs()

wind_inputs.renewable_inputs.production_inputs.print_flag = True
wind_inputs.renewable_inputs.production_inputs.capacity_kW = WIND_CAPACITY_KW
wind_inputs.renewable_inputs.production_inputs.is_sunk = False
wind_inputs.renewable_inputs.production_inputs.nominal_inflation_annual = 0.0
wind_inputs.renewable_inputs.production_inputs.nominal_discount_annual = 0.0
wind_inputs.renewable_inputs.production_inputs.replace_running_hrs = (
    WIND_REPLACEMENT_RUNNING_HR
)
wind_inputs.renewable_inputs.production_inputs.path_2_normalized_production_time_series = (
    WIND_PRODUCTION_CSV
)

wind_inputs.resource_key = 0
wind_inputs.firmness_factor = WIND_FIRMNESS_FACTOR
wind_inputs.design_speed_ms = WIND_DESIGN_SPEED_M_PER_S
wind_inputs.power_model = (
    PGMcpp.WindPowerProductionModel.WIND_POWER_CUBIC
)
wind_inputs.capital_cost = 0.0
wind_inputs.operation_maintenance_cost_kWh = 0.0

model.addWind(wind_inputs)


# =============================================================================
# 4. ADD THE LI-ION BATTERY
# =============================================================================

bess_inputs = PGMcpp.LiIonInputs()

bess_inputs.storage_inputs.print_flag = True
bess_inputs.storage_inputs.power_capacity_kW = BESS_POWER_KW
bess_inputs.storage_inputs.energy_capacity_kWh = BESS_ENERGY_KWH
bess_inputs.storage_inputs.is_sunk = False
bess_inputs.storage_inputs.nominal_inflation_annual = 0.0
bess_inputs.storage_inputs.nominal_discount_annual = 0.0

bess_inputs.init_SOC = BESS_INITIAL_SOC
bess_inputs.min_SOC = BESS_MINIMUM_SOC
bess_inputs.hysteresis_SOC = BESS_HYSTERESIS_SOC
bess_inputs.max_SOC = BESS_MAXIMUM_SOC
bess_inputs.charging_efficiency = BESS_CHARGING_EFFICIENCY
bess_inputs.discharging_efficiency = BESS_DISCHARGING_EFFICIENCY
bess_inputs.replace_SOH = BESS_REPLACEMENT_SOH
bess_inputs.power_degradation_flag = BESS_MODEL_POWER_DEGRADATION

bess_inputs.capital_cost = 0.0
bess_inputs.operation_maintenance_cost_kWh = 0.0

model.addLiIon(bess_inputs)


# =============================================================================
# 5. RUN THE MODEL AND WRITE THE FULL RESULTS
# =============================================================================

output_folder = Path(OUTPUT_LOCATION) / OUTPUT_NAME
output_folder.mkdir(parents=True, exist_ok=True)

model.run()
model.writeResults(str(output_folder))


# =============================================================================
# 6. WRITE THE SUMMARY CSV
# =============================================================================

# Convert missed-load power [kW] over each timestep [h] to unserved energy [kWh].
missed_load_vec_kw = model.controller.missed_load_vec_kW
dt_vec_hr = model.electrical_load.dt_vec_hrs

missed_load_kwh = sum(
    power_kw * dt_hr
    for power_kw, dt_hr in zip(missed_load_vec_kw, dt_vec_hr)
)
# Total duration of timesteps containing missed load.
missed_load_peak_kw = max(missed_load_vec_kw, default=0.0)
missed_load_hours = sum(
    dt_hr
    for power_kw, dt_hr in zip(missed_load_vec_kw, dt_vec_hr)
    if power_kw > 0.0
)

# Battery discharge is reported separately, so it is not included here.
renewable_dispatch_kwh = model.total_renewable_noncombustion_dispatch_kWh
combustion_dispatch_kwh = model.total_dispatch_kWh - renewable_dispatch_kwh
storage_charge_kwh = (
    model.total_renewable_noncombustion_charge_kWh
    + model.total_combustion_charge_kWh
)

# Collect key inputs and outputs for comparing cases.
summary = {
    "output_name": OUTPUT_NAME,
    "load_csv": ELECTRICAL_LOAD_CSV,
    "wind_production_csv": WIND_PRODUCTION_CSV,
    "control_mode": "PSIS",
    "firm_dispatch_ratio": FIRM_DISPATCH_RATIO,
    "load_reserve_ratio": LOAD_RESERVE_RATIO,
    "psis_diesel_on_soc": PSIS_DIESEL_ON_SOC,
    "psis_diesel_off_soc": PSIS_DIESEL_OFF_SOC,
    "psis_wind_shutdown_margin_ratio": PSIS_WIND_SHUTDOWN_MARGIN_RATIO,
    "psis_wind_shutdown_persistence_hr": PSIS_WIND_SHUTDOWN_PERSISTENCE_HR,
    "diesel_capacities_kW": ";".join(map(str, DIESEL_CAPACITIES_KW)),
    "diesel_total_capacity_kW": sum(DIESEL_CAPACITIES_KW),
    "wind_capacity_kW": WIND_CAPACITY_KW,
    "bess_power_kW": BESS_POWER_KW,
    "bess_energy_kWh": BESS_ENERGY_KWH,
    "bess_power_degradation_enabled": BESS_MODEL_POWER_DEGRADATION,
    "bess_replacement_SOH": BESS_REPLACEMENT_SOH,
    "modelled_years": model.electrical_load.n_years,
    "total_fuel_consumed_L": model.total_fuel_consumed_L,
    "annual_avg_fuel_L_per_yr": (
        model.total_fuel_consumed_L / model.electrical_load.n_years
    ),
    "total_CO2_kg": model.total_emissions.CO2_kg,
    "total_CO_kg": model.total_emissions.CO_kg,
    "total_NOx_kg": model.total_emissions.NOx_kg,
    "total_SOx_kg": model.total_emissions.SOx_kg,
    "total_CH4_kg": model.total_emissions.CH4_kg,
    "total_PM_kg": model.total_emissions.PM_kg,
    "annual_avg_CO2_kg_per_yr": (
        model.total_emissions.CO2_kg / model.electrical_load.n_years
    ),
    "renewable_penetration": model.renewable_penetration,
    "total_dispatch_kWh": model.total_dispatch_kWh,
    "renewable_dispatch_kWh": renewable_dispatch_kwh,
    "combustion_dispatch_kWh": combustion_dispatch_kwh,
    "renewable_charge_kWh": model.total_renewable_noncombustion_charge_kWh,
    "combustion_charge_kWh": model.total_combustion_charge_kWh,
    "storage_charge_kWh": storage_charge_kwh,
    "storage_discharge_kWh": model.total_discharge_kWh,
    "missed_load_kWh": missed_load_kwh,
    "missed_load_peak_kW": missed_load_peak_kw,
    "missed_load_hours": missed_load_hours,
}

summary_csv = output_folder / "summary.csv"
with summary_csv.open("w", newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=summary)
    writer.writeheader()
    writer.writerow(summary)

print("\nRun complete")
print(f"Results folder:    {output_folder}")
print(f"Fuel consumed:     {model.total_fuel_consumed_L:,.2f} L")
print(f"Missed load:       {missed_load_kwh:,.3f} kWh")
print(f"Missed-load peak:  {missed_load_peak_kw:,.3f} kW")
print(f"Missed-load hours: {missed_load_hours:,.3f} hr")