import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # pip install tomli


# ============================================================
# Case file
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
CASE_FILE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SCRIPT_DIR / "GUIbasis.toml"

with open(CASE_FILE, "rb") as f:
    cfg = tomllib.load(f)


# ------------------------------------------------------------
# Load local PGMcpp Python bindings
# ------------------------------------------------------------

sys.path.insert(0, cfg["paths"]["pgmcpp_pybindings"])

import PGMcpp

print("PGMcpp loaded from:", PGMcpp.__file__)
print("Case file:", CASE_FILE)


# ============================================================
# Helpers
# ============================================================

def enabled(item):
    return bool(item.get("enabled", True))


def get_enum(enum_class_name, member_name):
    enum_class = getattr(PGMcpp, enum_class_name, None)

    if enum_class is not None and hasattr(enum_class, member_name):
        return getattr(enum_class, member_name)

    if hasattr(PGMcpp, member_name):
        return getattr(PGMcpp, member_name)

    raise ValueError(f"Could not find PGMcpp enum: {enum_class_name}.{member_name}")


def set_if_present(obj, attr, source, key=None):
    key = attr if key is None else key

    if key in source:
        setattr(obj, attr, source[key])


def set_common_production_inputs(prod_inputs, source):
    for key in [
        "print_flag",
        "is_sunk",
        "capacity_kW",
        "nominal_inflation_annual",
        "nominal_discount_annual",
        "replace_running_hrs",
        "path_2_normalized_production_time_series",
    ]:
        set_if_present(prod_inputs, key, source)


def set_common_storage_inputs(storage_inputs, source):
    for key in [
        "print_flag",
        "is_sunk",
        "power_capacity_kW",
        "energy_capacity_kWh",
        "nominal_inflation_annual",
        "nominal_discount_annual",
    ]:
        set_if_present(storage_inputs, key, source)


def compute_production_capital_cost_CAD(asset, capacity_kW):
    """
    Production assets use kW basis only.

    cost_mode:
      INTERNAL      -> use PGMcpp internal capital-cost model
      CAD_PER_UNIT  -> cost_value_CAD [CAD/kW] * capacity_kW * remote_cost_factor
      TOTAL_CAD     -> cost_value_CAD [CAD]
    """
    mode = str(asset.get("cost_mode", "INTERNAL")).upper()

    if "capital_cost_CAD" in asset:
        return float(asset["capital_cost_CAD"])

    if mode == "INTERNAL":
        return -1.0

    if "cost_value_CAD" not in asset:
        return -1.0

    cost_value_CAD = float(asset["cost_value_CAD"])

    if mode == "TOTAL_CAD":
        return cost_value_CAD

    if mode == "CAD_PER_UNIT":
        default_remote_factor = float(cfg.get("economics", {}).get("remote_cost_factor", 1.0))
        remote_factor = float(asset.get("remote_cost_factor", default_remote_factor))
        return cost_value_CAD * float(capacity_kW) * remote_factor

    raise ValueError(f"Unsupported production cost_mode: {mode}")


def compute_battery_capital_cost_CAD(asset, power_kW, energy_kWh):
    """
    Battery assets can use kWh or kW basis.

    cost_mode:
      INTERNAL      -> use PGMcpp internal capital-cost model
      CAD_PER_UNIT  -> cost_value_CAD * selected basis * remote_cost_factor
      TOTAL_CAD     -> cost_value_CAD [CAD]
    """
    mode = str(asset.get("cost_mode", "INTERNAL")).upper()

    if "capital_cost_CAD" in asset:
        return float(asset["capital_cost_CAD"])

    if mode == "INTERNAL":
        return -1.0

    if "cost_value_CAD" not in asset:
        return -1.0

    cost_value_CAD = float(asset["cost_value_CAD"])

    if mode == "TOTAL_CAD":
        return cost_value_CAD

    if mode == "CAD_PER_UNIT":
        basis = str(asset.get("capital_cost_basis", "kWh"))
        if basis == "kWh":
            basis_value = float(energy_kWh)
        elif basis == "kW":
            basis_value = float(power_kW)
        else:
            raise ValueError(f"Battery capital_cost_basis must be 'kWh' or 'kW', not {basis!r}")

        default_remote_factor = float(cfg.get("economics", {}).get("remote_cost_factor", 1.0))
        remote_factor = float(asset.get("remote_cost_factor", default_remote_factor))
        return cost_value_CAD * basis_value * remote_factor

    raise ValueError(f"Unsupported battery cost_mode: {mode}")


def set_production_costs(obj, asset, capacity_kW):
    capital_cost = compute_production_capital_cost_CAD(asset, capacity_kW)

    if capital_cost >= 0:
        obj.capital_cost = capital_cost

    if "operation_maintenance_cost_kWh" in asset:
        obj.operation_maintenance_cost_kWh = float(asset["operation_maintenance_cost_kWh"])

    return capital_cost


def set_battery_costs(obj, asset, power_kW, energy_kWh):
    capital_cost = compute_battery_capital_cost_CAD(asset, power_kW, energy_kWh)

    if capital_cost >= 0:
        obj.capital_cost = capital_cost

    if "operation_maintenance_cost_kWh" in asset:
        obj.operation_maintenance_cost_kWh = float(asset["operation_maintenance_cost_kWh"])

    return capital_cost


def add_resource(model, resource):
    rtype = str(resource["type"]).upper()
    key = int(resource["key"])
    path = resource["path"]

    if rtype == "HYDRO":
        model.addResource(PGMcpp.NoncombustionType.HYDRO, path, key)
    else:
        model.addResource(getattr(PGMcpp.RenewableType, rtype), path, key)


def apply_renewable_common(inputs, asset):
    set_common_production_inputs(inputs.renewable_inputs.production_inputs, asset)
    set_if_present(inputs, "resource_key", asset)
    set_if_present(inputs, "firmness_factor", asset)


def apply_hydro_common(inputs, asset):
    set_common_production_inputs(inputs.noncombustion_inputs.production_inputs, asset)
    set_if_present(inputs, "resource_key", asset)


# ============================================================
# Model inputs
# ============================================================

model_inputs = PGMcpp.ModelInputs()
model_inputs.path_2_electrical_load_time_series = cfg["paths"]["electrical_load_time_series"]

control_mode = str(cfg["model"].get("control_mode", "LOAD_FOLLOWING")).upper()

if control_mode == "LOAD_FOLLOWING":
    model_inputs.control_mode = PGMcpp.ControlMode.LOAD_FOLLOWING
elif control_mode == "CYCLE_CHARGING":
    model_inputs.control_mode = PGMcpp.ControlMode.CYCLE_CHARGING
else:
    raise ValueError(f"Unsupported control mode: {control_mode}")

model_inputs.firm_dispatch_ratio = float(cfg["model"].get("firm_dispatch_ratio", 0.1))
model_inputs.load_reserve_ratio = float(cfg["model"].get("load_reserve_ratio", 0.1))

model = PGMcpp.Model(model_inputs)


# ============================================================
# Resources
# ============================================================

for resource in cfg.get("renewable_resources", []):
    if enabled(resource):
        add_resource(model, resource)


# ============================================================
# Diesel generators
# ============================================================

diesel_count = 0
diesel_capacities_kW = []

for gen in cfg.get("diesel_generators", []):
    if not enabled(gen):
        continue

    diesel_inputs = PGMcpp.DieselInputs()

    set_common_production_inputs(
        diesel_inputs.combustion_inputs.production_inputs,
        gen,
    )

    set_if_present(diesel_inputs, "replace_running_hrs", gen)
    set_if_present(diesel_inputs, "capital_cost", gen, "capital_cost_CAD")
    set_if_present(diesel_inputs, "operation_maintenance_cost_kWh", gen)
    set_if_present(diesel_inputs, "fuel_cost_L", gen, "fuel_cost_CAD_per_L")
    set_if_present(diesel_inputs, "minimum_load_ratio", gen)
    set_if_present(diesel_inputs, "minimum_runtime_hrs", gen)
    set_if_present(diesel_inputs, "linear_fuel_slope_LkWh", gen)
    set_if_present(diesel_inputs, "linear_fuel_intercept_LkWh", gen)

    set_if_present(diesel_inputs, "CO2_emissions_intensity_kgL", gen)
    set_if_present(diesel_inputs, "CO_emissions_intensity_kgL", gen)
    set_if_present(diesel_inputs, "NOx_emissions_intensity_kgL", gen)
    set_if_present(diesel_inputs, "SOx_emissions_intensity_kgL", gen)
    set_if_present(diesel_inputs, "CH4_emissions_intensity_kgL", gen)
    set_if_present(diesel_inputs, "PM_emissions_intensity_kgL", gen)

    model.addDiesel(diesel_inputs)

    diesel_count += 1
    diesel_capacities_kW.append(gen.get("capacity_kW", None))


# ============================================================
# Wind assets
# ============================================================

wind_count = 0
solar_count = 0
tidal_count = 0
wave_count = 0
hydro_count = 0
liion_count = 0

production_capex_CAD = 0.0
hydro_capex_CAD = 0.0
liion_capex_CAD = 0.0

for asset in cfg.get("wind_assets", []):
    if not enabled(asset):
        continue

    capacity_kW = float(asset["capacity_kW"])

    inputs = PGMcpp.WindInputs()
    apply_renewable_common(inputs, asset)

    set_if_present(inputs, "design_speed_ms", asset)

    if "power_model" in asset:
        model_name = "WIND_POWER_" + str(asset["power_model"]).upper()
        inputs.power_model = get_enum("WindPowerProductionModel", model_name)

    capex = set_production_costs(inputs, asset, capacity_kW)
    model.addWind(inputs)

    wind_count += 1
    if capex >= 0:
        production_capex_CAD += capex


# ============================================================
# Solar assets
# ============================================================

for asset in cfg.get("solar_assets", []):
    if not enabled(asset):
        continue

    capacity_kW = float(asset["capacity_kW"])

    inputs = PGMcpp.SolarInputs()
    apply_renewable_common(inputs, asset)

    for key in [
        "derating",
        "julian_day",
        "latitude_deg",
        "longitude_deg",
        "panel_azimuth_deg",
        "panel_tilt_deg",
        "albedo_ground_reflectance",
    ]:
        set_if_present(inputs, key, asset)

    if "power_model" in asset:
        model_name = "SOLAR_POWER_" + str(asset["power_model"]).upper()
        inputs.power_model = get_enum("SolarPowerProductionModel", model_name)

    capex = set_production_costs(inputs, asset, capacity_kW)
    model.addSolar(inputs)

    solar_count += 1
    if capex >= 0:
        production_capex_CAD += capex


# ============================================================
# Tidal assets
# ============================================================

for asset in cfg.get("tidal_assets", []):
    if not enabled(asset):
        continue

    capacity_kW = float(asset["capacity_kW"])

    inputs = PGMcpp.TidalInputs()
    apply_renewable_common(inputs, asset)

    set_if_present(inputs, "design_speed_ms", asset)

    if "power_model" in asset:
        model_name = "TIDAL_POWER_" + str(asset["power_model"]).upper()
        inputs.power_model = get_enum("TidalPowerProductionModel", model_name)

    capex = set_production_costs(inputs, asset, capacity_kW)
    model.addTidal(inputs)

    tidal_count += 1
    if capex >= 0:
        production_capex_CAD += capex


# ============================================================
# Wave assets
# ============================================================

for asset in cfg.get("wave_assets", []):
    if not enabled(asset):
        continue

    capacity_kW = float(asset["capacity_kW"])

    inputs = PGMcpp.WaveInputs()
    apply_renewable_common(inputs, asset)

    set_if_present(inputs, "design_significant_wave_height_m", asset)
    set_if_present(inputs, "design_energy_period_s", asset)
    set_if_present(inputs, "path_2_normalized_performance_matrix", asset)

    if "power_model" in asset:
        model_name = "WAVE_POWER_" + str(asset["power_model"]).upper()
        inputs.power_model = get_enum("WavePowerProductionModel", model_name)

    capex = set_production_costs(inputs, asset, capacity_kW)
    model.addWave(inputs)

    wave_count += 1
    if capex >= 0:
        production_capex_CAD += capex


# ============================================================
# Hydro assets
# ============================================================

for asset in cfg.get("hydro_assets", []):
    if not enabled(asset):
        continue

    capacity_kW = float(asset["capacity_kW"])

    inputs = PGMcpp.HydroInputs()
    apply_hydro_common(inputs, asset)

    for key in [
        "fluid_density_kgm3",
        "net_head_m",
        "reservoir_capacity_m3",
        "init_reservoir_state",
    ]:
        set_if_present(inputs, key, asset)

    if "turbine_type" in asset:
        model_name = "HYDRO_TURBINE_" + str(asset["turbine_type"]).upper()
        inputs.turbine_type = get_enum("HydroTurbineType", model_name)

    capex = set_production_costs(inputs, asset, capacity_kW)
    model.addHydro(inputs)

    hydro_count += 1
    if capex >= 0:
        hydro_capex_CAD += capex


# ============================================================
# Lithium-ion batteries
# ============================================================

for asset in cfg.get("liion_batteries", []):
    if not enabled(asset):
        continue

    power_kW = float(asset["power_capacity_kW"])
    energy_kWh = float(asset["energy_capacity_kWh"])

    inputs = PGMcpp.LiIonInputs()

    set_common_storage_inputs(inputs.storage_inputs, asset)

    for key in [
        "init_SOC",
        "min_SOC",
        "hysteresis_SOC",
        "max_SOC",
        "charging_efficiency",
        "discharging_efficiency",
        "replace_SOH",
        "power_degradation_flag",
        "degradation_alpha",
        "degradation_beta",
        "degradation_B_hat_cal_0",
        "degradation_r_cal",
        "degradation_Ea_cal_0",
        "degradation_a_cal",
        "degradation_s_cal",
        "gas_constant_JmolK",
    ]:
        set_if_present(inputs, key, asset)

    capex = set_battery_costs(inputs, asset, power_kW, energy_kWh)

    model.addLiIon(inputs)

    liion_count += 1
    if capex >= 0:
        liion_capex_CAD += capex


# ============================================================
# Diagnostics
# ============================================================

print("\n--- Model inputs ---")
print("Electrical load:", cfg["paths"]["electrical_load_time_series"])
print("Control mode:", control_mode)
print("Firm dispatch ratio [-]:", model_inputs.firm_dispatch_ratio)
print("Load reserve ratio [-]:", model_inputs.load_reserve_ratio)

print("\n--- Added assets ---")
print("Diesel generators:", diesel_count)
print("Diesel capacities [kW]:", diesel_capacities_kW)
print("Wind assets:", wind_count)
print("Solar assets:", solar_count)
print("Tidal assets:", tidal_count)
print("Wave assets:", wave_count)
print("Hydro assets:", hydro_count)
print("Li-ion batteries:", liion_count)

print("\n--- User-defined CAPEX included in script ---")
print("Production CAPEX [CAD]:", production_capex_CAD)
print("Hydro CAPEX [CAD]:", hydro_capex_CAD)
print("Li-ion CAPEX [CAD]:", liion_capex_CAD)
print("Total user-defined CAPEX [CAD]:", production_capex_CAD + hydro_capex_CAD + liion_capex_CAD)

print("\nNote: assets with cost_mode = INTERNAL use PGMcpp internal cost model.")


# ============================================================
# Run model
# ============================================================

model.run()

results_name = cfg.get("output", {}).get("results_name", "PGMcpp_GUI_case")
model.writeResults(results_name)

print("\nRun complete.")
print("Results written to:", results_name)
