import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import pandas as pd
import streamlit as st
import tomlkit


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CASE_FILE = SCRIPT_DIR / "GUIbasis.toml"

RESOURCE_TYPES = ["WIND", "SOLAR", "TIDAL", "WAVE", "HYDRO"]
COST_MODES = ["INTERNAL", "CAD_PER_UNIT", "TOTAL_CAD"]
BATTERY_COST_BASES = ["kWh", "kW"]


# ============================================================
# I/O
# ============================================================

def load_toml(path: Path):
    if not path.exists():
        st.error(f"Could not find TOML file: {path}")
        st.stop()

    with open(path, "r", encoding="utf-8") as f:
        return tomlkit.parse(f.read())


def save_toml(path: Path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(cfg))


def ensure_section(cfg, key):
    if key not in cfg:
        cfg[key] = tomlkit.table()
    return cfg[key]


def ensure_aot(cfg, key):
    if key not in cfg:
        cfg[key] = tomlkit.aot()
    return cfg[key]


# ============================================================
# Value conversion
# ============================================================

def is_blank(value):
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass

    return isinstance(value, str) and value.strip() == ""


def python_value(value):
    if is_blank(value):
        return None

    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass

    if isinstance(value, bool):
        return bool(value)

    if isinstance(value, int):
        return int(value)

    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return float(value)

    if isinstance(value, str):
        txt = value.strip()

        if txt.lower() == "true":
            return True
        if txt.lower() == "false":
            return False

        try:
            if "." in txt or "e" in txt.lower():
                return float(txt)
            return int(txt)
        except ValueError:
            return txt

    return value


# ============================================================
# DataFrame conversion
# ============================================================

def aot_to_df(cfg, key, columns):
    rows = []

    for item in cfg.get(key, []):
        row = {}
        for col in columns:
            row[col] = item.get(col, None)
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def clean_cost_fields(item, is_battery=False):
    """
    Normalize custom GUI cost fields.
    These are consumed by full_gui_project.py, not assigned directly to PGMcpp.
    """
    for old_key in [
        "unit_cost_CAD_per_kW",
        "unit_cost_CAD_per_kWh",
        "unit_cost_USD_per_kW",
        "unit_cost_USD_per_kWh",
        "unit_cost",
    ]:
        if old_key in item:
            del item[old_key]

    mode = str(item.get("cost_mode", "INTERNAL")).upper()
    item["cost_mode"] = mode

    if mode == "INTERNAL":
        if "cost_value_CAD" in item:
            del item["cost_value_CAD"]
        if "capital_cost_CAD" in item:
            del item["capital_cost_CAD"]

    elif mode == "TOTAL_CAD":
        if "cost_value_CAD" in item:
            item["capital_cost_CAD"] = item["cost_value_CAD"]

    elif mode == "CAD_PER_UNIT":
        if "capital_cost_CAD" in item:
            del item["capital_cost_CAD"]

    if is_battery:
        if item.get("capital_cost_basis", None) not in ["kWh", "kW"]:
            item["capital_cost_basis"] = "kWh"
    else:
        # Production assets are always kW basis. Do not expose or store kWh basis.
        if "capital_cost_basis" in item:
            del item["capital_cost_basis"]

    return item


def df_to_aot_preserve(df: pd.DataFrame, original_aot, visible_columns, cost_table=False, is_battery=False):
    """
    Rebuild array-of-tables while preserving hidden advanced keys by row index.
    """
    aot = tomlkit.aot()

    for idx, row in df.iterrows():
        if all(is_blank(row.get(col, None)) for col in visible_columns):
            continue

        if idx < len(original_aot):
            item = tomlkit.table()
            for key, value in original_aot[idx].items():
                item[key] = value
        else:
            item = tomlkit.table()

        for col in visible_columns:
            value = python_value(row.get(col, None))

            if value is None:
                if col in item:
                    del item[col]
            else:
                item[col] = value

        if cost_table:
            item = clean_cost_fields(item, is_battery=is_battery)

        aot.append(item)

    return aot


# ============================================================
# Migration helpers
# ============================================================

def migrate_legacy_cost_fields(item, is_battery=False):
    """
    Converts older cost fields into v4 CAD-only fields.
    Old USD field values are copied as numeric CAD values with no FX conversion.
    """
    if "cost_value_CAD" in item:
        return clean_cost_fields(item, is_battery=is_battery)

    if "capital_cost_CAD" in item:
        item["cost_mode"] = "TOTAL_CAD"
        item["cost_value_CAD"] = item["capital_cost_CAD"]
        return clean_cost_fields(item, is_battery=is_battery)

    if "unit_cost_CAD_per_kWh" in item:
        item["cost_mode"] = "CAD_PER_UNIT"
        item["cost_value_CAD"] = item["unit_cost_CAD_per_kWh"]
        if is_battery:
            item["capital_cost_basis"] = "kWh"
        return clean_cost_fields(item, is_battery=is_battery)

    if "unit_cost_CAD_per_kW" in item:
        item["cost_mode"] = "CAD_PER_UNIT"
        item["cost_value_CAD"] = item["unit_cost_CAD_per_kW"]
        if is_battery:
            item["capital_cost_basis"] = "kW"
        return clean_cost_fields(item, is_battery=is_battery)

    # Legacy compatibility only; no FX conversion.
    if "unit_cost_USD_per_kWh" in item:
        item["cost_mode"] = "CAD_PER_UNIT"
        item["cost_value_CAD"] = item["unit_cost_USD_per_kWh"]
        if is_battery:
            item["capital_cost_basis"] = "kWh"
        return clean_cost_fields(item, is_battery=is_battery)

    if "unit_cost_USD_per_kW" in item:
        item["cost_mode"] = "CAD_PER_UNIT"
        item["cost_value_CAD"] = item["unit_cost_USD_per_kW"]
        if is_battery:
            item["capital_cost_basis"] = "kW"
        return clean_cost_fields(item, is_battery=is_battery)

    if "cost_mode" not in item:
        item["cost_mode"] = "INTERNAL"

    return clean_cost_fields(item, is_battery=is_battery)


def migrate_legacy_renewable_assets(cfg):
    """
    Supports older files that used [[renewable_assets]] with type = WIND/SOLAR/etc.
    """
    if "renewable_assets" not in cfg:
        return cfg

    mapping = {
        "WIND": "wind_assets",
        "SOLAR": "solar_assets",
        "TIDAL": "tidal_assets",
        "WAVE": "wave_assets",
    }

    for old_item in cfg.get("renewable_assets", []):
        rtype = str(old_item.get("type", "")).upper()
        target = mapping.get(rtype)

        if target is None:
            continue

        ensure_aot(cfg, target)

        item = tomlkit.table()
        for key, value in old_item.items():
            if key != "type":
                item[key] = value

        cfg[target].append(item)

    del cfg["renewable_assets"]

    return cfg


def migrate_costs(cfg):
    for section in ["wind_assets", "solar_assets", "tidal_assets", "wave_assets", "hydro_assets"]:
        for item in cfg.get(section, []):
            migrate_legacy_cost_fields(item, is_battery=False)

    for item in cfg.get("liion_batteries", []):
        migrate_legacy_cost_fields(item, is_battery=True)

    return cfg


# ============================================================
# Resource keys
# ============================================================

def default_resource_label(resource_type, path, index):
    stem = ""

    if not is_blank(path):
        try:
            stem = Path(str(path)).stem
        except Exception:
            stem = ""

    if stem:
        return f"{resource_type}_{index}_{stem}"

    return f"{resource_type}_{index}"


def normalize_resource_labels(resources):
    type_counts = {}

    for item in resources:
        rtype = str(item.get("type", "WIND")).upper()
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
        item["type"] = rtype

        if is_blank(item.get("resource_label", None)):
            item["resource_label"] = default_resource_label(
                rtype,
                item.get("path", ""),
                type_counts[rtype],
            )

    return resources


def auto_assign_resource_keys(cfg):
    resources = normalize_resource_labels(list(cfg.get("renewable_resources", [])))

    label_to_key = {}
    first_key_by_type = {}

    for idx, resource in enumerate(resources, start=1):
        rtype = str(resource.get("type", "WIND")).upper()
        label = str(resource.get("resource_label", default_resource_label(rtype, resource.get("path", ""), idx)))

        resource["type"] = rtype
        resource["key"] = idx
        resource["resource_label"] = label

        label_to_key[label] = idx

        if rtype not in first_key_by_type:
            first_key_by_type[rtype] = idx

    def assign_asset_key(asset, asset_type):
        label = asset.get("resource_label", None)

        if not is_blank(label) and str(label) in label_to_key:
            asset["resource_key"] = label_to_key[str(label)]
            return

        if asset_type in first_key_by_type:
            asset["resource_key"] = first_key_by_type[asset_type]

    for section, rtype in [
        ("wind_assets", "WIND"),
        ("solar_assets", "SOLAR"),
        ("tidal_assets", "TIDAL"),
        ("wave_assets", "WAVE"),
        ("hydro_assets", "HYDRO"),
    ]:
        for asset in cfg.get(section, []):
            assign_asset_key(asset, rtype)

    cfg["renewable_resources"] = resources

    return cfg


def resource_options(cfg, resource_type=None):
    resources = normalize_resource_labels(list(cfg.get("renewable_resources", [])))
    labels = []

    for item in resources:
        rtype = str(item.get("type", "")).upper()

        if resource_type is None or rtype == resource_type:
            label = str(item.get("resource_label", ""))
            if label:
                labels.append(label)

    return labels


# ============================================================
# Explicit row-add helpers
# ============================================================

def append_aot_row(cfg, section, defaults):
    """
    Add one TOML array-of-table row.

    The GUI uses explicit add buttons instead of Streamlit's dynamic-row mode
    because dynamic spreadsheet rows can be created accidentally while scrolling.
    """
    aot = ensure_aot(cfg, section)
    item = tomlkit.table()

    for key, value in defaults.items():
        if value is not None:
            item[key] = value

    aot.append(item)
    return item


def next_resource_label_for_type(cfg, resource_type):
    """Create a simple unique label such as WIND_1 or SOLAR_2."""
    rtype = str(resource_type).upper()
    existing = normalize_resource_labels(list(cfg.get("renewable_resources", [])))
    count = sum(1 for item in existing if str(item.get("type", "")).upper() == rtype)
    return f"{rtype}_{count + 1}"


def first_resource_label(cfg, resource_type):
    """Return the first matching resource label for an asset, if one exists."""
    labels = resource_options(cfg, resource_type)
    if labels:
        return labels[0]
    return ""


def resource_defaults(cfg, resource_type):
    rtype = str(resource_type).upper()
    return {
        "enabled": True,
        "type": rtype,
        "resource_label": next_resource_label_for_type(cfg, rtype),
        "path": "",
    }


def diesel_defaults():
    return {
        "enabled": True,
        "capacity_kW": 0,
        "is_sunk": False,
        "fuel_cost_CAD_per_L": 0,
        "operation_maintenance_cost_kWh": 0,
    }


def production_asset_defaults(cfg, resource_type):
    return {
        "enabled": True,
        "capacity_kW": 0,
        "resource_label": first_resource_label(cfg, resource_type),
        "is_sunk": False,
        "cost_mode": "INTERNAL",
        "operation_maintenance_cost_kWh": 0,
    }


def liion_defaults():
    return {
        "enabled": True,
        "power_capacity_kW": 0,
        "energy_capacity_kWh": 0,
        "is_sunk": False,
        "cost_mode": "INTERNAL",
        "capital_cost_basis": "kWh",
        "operation_maintenance_cost_kWh": 0,
    }


def add_row_and_reload(section, defaults):
    """
    Add a row to the in-memory TOML document, then rerun Streamlit.
    The user still controls when the TOML file is saved to disk.
    """
    append_aot_row(cfg, section, defaults)
    auto_assign_resource_keys(cfg)
    st.session_state["cfg"] = cfg
    st.rerun()


DASHBOARD_URL = "http://127.0.0.1:8051"


def launch_dashboard(dashboard_path: Path, case_file: Path):
    """
    Launch dashboard.py without blocking this GUI, then open the dashboard URL.

    The dashboard is given the TOML case file as an argument. The dashboard then
    reads [output].results_name from the TOML file to find the results folder.
    No stdout/stderr log files are created.
    """
    if not dashboard_path.exists():
        st.warning(f"PGMCpp finished, but dashboard.py was not found: {dashboard_path}")
        return None

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with open(os.devnull, "w", encoding="utf-8") as devnull:
        process = subprocess.Popen(
            [sys.executable, str(dashboard_path), str(case_file)],
            cwd=str(SCRIPT_DIR),
            stdout=devnull,
            stderr=devnull,
            text=True,
            creationflags=creationflags,
        )

    st.session_state["dashboard_pid"] = process.pid

    # Give Dash a moment to bind to the port before opening the browser.
    time.sleep(1.0)
    webbrowser.open(DASHBOARD_URL, new=2)

    st.success(f"Dashboard launched: {DASHBOARD_URL}")
    return process.pid


# ============================================================
# Columns
# ============================================================

RESOURCE_BASIC = ["enabled", "type", "resource_label", "path"]

DIESEL_BASIC = ["enabled", "capacity_kW", "is_sunk", "fuel_cost_CAD_per_L", "operation_maintenance_cost_kWh"]
DIESEL_ADVANCED = [
    "print_flag",
    "nominal_inflation_annual",
    "nominal_discount_annual",
    "replace_running_hrs",
    "path_2_normalized_production_time_series",
    "minimum_load_ratio",
    "minimum_runtime_hrs",
    "linear_fuel_slope_LkWh",
    "linear_fuel_intercept_LkWh",
    "capital_cost_CAD",
    "CO2_emissions_intensity_kgL",
    "CO_emissions_intensity_kgL",
    "NOx_emissions_intensity_kgL",
    "SOx_emissions_intensity_kgL",
    "CH4_emissions_intensity_kgL",
    "PM_emissions_intensity_kgL",
]

PRODUCTION_COST_BASIC = [
    "enabled",
    "capacity_kW",
    "resource_label",
    "is_sunk",
    "cost_mode",
    "cost_value_CAD",
    "remote_cost_factor",
    "operation_maintenance_cost_kWh",
]

PRODUCTION_COMMON_ADVANCED = [
    "print_flag",
    "nominal_inflation_annual",
    "nominal_discount_annual",
    "replace_running_hrs",
    "path_2_normalized_production_time_series",
]

WIND_ADVANCED = PRODUCTION_COMMON_ADVANCED + ["firmness_factor", "design_speed_ms", "power_model"]
SOLAR_ADVANCED = PRODUCTION_COMMON_ADVANCED + [
    "firmness_factor",
    "derating",
    "power_model",
    "julian_day",
    "latitude_deg",
    "longitude_deg",
    "panel_azimuth_deg",
    "panel_tilt_deg",
    "albedo_ground_reflectance",
]
TIDAL_ADVANCED = PRODUCTION_COMMON_ADVANCED + ["firmness_factor", "design_speed_ms", "power_model"]
WAVE_ADVANCED = PRODUCTION_COMMON_ADVANCED + [
    "firmness_factor",
    "design_significant_wave_height_m",
    "design_energy_period_s",
    "power_model",
    "path_2_normalized_performance_matrix",
]
HYDRO_ADVANCED = PRODUCTION_COMMON_ADVANCED + [
    "net_head_m",
    "fluid_density_kgm3",
    "reservoir_capacity_m3",
    "init_reservoir_state",
    "turbine_type",
]

LIION_BASIC = [
    "enabled",
    "power_capacity_kW",
    "energy_capacity_kWh",
    "is_sunk",
    "cost_mode",
    "cost_value_CAD",
    "capital_cost_basis",
    "remote_cost_factor",
    "operation_maintenance_cost_kWh",
]
LIION_ADVANCED = [
    "print_flag",
    "nominal_inflation_annual",
    "nominal_discount_annual",
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
]


# ============================================================
# Column help text
# ============================================================

HELP_TEXT = {
    "enabled": "If false, this row is kept in the TOML file but not added to the PGMCpp model.",
    "type": "Resource time-series type. Must match the asset type using the resource.",
    "resource_label": "Human-readable link between a resource file and an asset. The GUI converts this to the integer resource_key required by PGMCpp.",
    "path": "CSV or time-series file path used by PGMCpp for the selected resource.",
    "key": "Auto-assigned integer resource key passed to PGMCpp.",
    "resource_key": "Auto-assigned integer key linking an asset to a resource file.",
    "capacity_kW": "Rated production capacity passed to PGMCpp production_inputs.capacity_kW [kW].",
    "power_capacity_kW": "Battery inverter / power capacity passed to PGMCpp storage_inputs.power_capacity_kW [kW].",
    "energy_capacity_kWh": "Battery energy capacity passed to PGMCpp storage_inputs.energy_capacity_kWh [kWh].",
    "is_sunk": "If true, the asset is treated as existing/sunk in PGMCpp production or storage inputs.",
    "fuel_cost_CAD_per_L": "Diesel fuel cost assigned to diesel_inputs.fuel_cost_L [CAD/L].",
    "cost_mode": "INTERNAL uses PGMCpp default cost model; CAD_PER_UNIT multiplies unit cost by size and remote factor; TOTAL_CAD uses cost_value_CAD as total CAPEX.",
    "cost_value_CAD": "For production assets: CAD/kW when cost_mode is CAD_PER_UNIT. For batteries: CAD/kWh or CAD/kW depending on capital_cost_basis. For TOTAL_CAD: total CAD.",
    "capital_cost_basis": "Battery-only cost basis. Use kWh for energy-costed systems or kW for power-costed systems.",
    "remote_cost_factor": "Multiplier applied to CAD_PER_UNIT capital cost. Leave blank to use the default remote factor.",
    "operation_maintenance_cost_kWh": "O&M cost passed to PGMCpp as operation_maintenance_cost_kWh [CAD/kWh].",
    "print_flag": "PGMCpp print/debug flag for the component input object.",
    "nominal_inflation_annual": "Nominal annual inflation assumption for this asset [-].",
    "nominal_discount_annual": "Nominal annual discount rate for this asset [-].",
    "replace_running_hrs": "Running-hour replacement threshold used by PGMCpp [h].",
    "path_2_normalized_production_time_series": "Optional normalized production time-series path passed to production_inputs.path_2_normalized_production_time_series.",
    "minimum_load_ratio": "Minimum diesel loading ratio [-].",
    "minimum_runtime_hrs": "Minimum diesel runtime constraint [h].",
    "linear_fuel_slope_LkWh": "Diesel fuel-curve slope [L/kWh].",
    "linear_fuel_intercept_LkWh": "Diesel fuel-curve intercept term [L/kWh].",
    "capital_cost_CAD": "Direct capital-cost override passed to PGMCpp as capital_cost [CAD].",
    "CO2_emissions_intensity_kgL": "CO2 emissions intensity [kg/L diesel].",
    "CO_emissions_intensity_kgL": "CO emissions intensity [kg/L diesel].",
    "NOx_emissions_intensity_kgL": "NOx emissions intensity [kg/L diesel].",
    "SOx_emissions_intensity_kgL": "SOx emissions intensity [kg/L diesel].",
    "CH4_emissions_intensity_kgL": "CH4 emissions intensity [kg/L diesel].",
    "PM_emissions_intensity_kgL": "Particulate-matter emissions intensity [kg/L diesel].",
    "firmness_factor": "Renewable firmness factor passed to PGMCpp renewable asset inputs [-].",
    "design_speed_ms": "Design wind/tidal speed used by the selected PGMCpp power model [m/s].",
    "power_model": "PGMCpp production model enum suffix. Example: CUBIC maps to WIND_POWER_CUBIC for wind.",
    "derating": "Solar derating factor passed to SolarInputs [-].",
    "julian_day": "Solar model day-of-year input used by PGMCpp detailed solar-position calculations.",
    "latitude_deg": "Solar site latitude [deg].",
    "longitude_deg": "Solar site longitude [deg].",
    "panel_azimuth_deg": "Solar panel azimuth angle [deg].",
    "panel_tilt_deg": "Solar panel tilt angle [deg].",
    "albedo_ground_reflectance": "Solar ground-reflectance/albedo factor used for ground-reflected irradiance [-].",
    "design_significant_wave_height_m": "Wave model design significant wave height [m].",
    "design_energy_period_s": "Wave model design energy period [s].",
    "path_2_normalized_performance_matrix": "Wave performance-matrix file path used by PGMCpp when applicable.",
    "net_head_m": "Hydro net head [m].",
    "fluid_density_kgm3": "Hydro fluid density [kg/m^3].",
    "reservoir_capacity_m3": "Hydro reservoir capacity [m^3].",
    "init_reservoir_state": "Initial reservoir state used by PGMCpp [- or model units].",
    "turbine_type": "Hydro turbine enum suffix. Example: PELTON maps to HYDRO_TURBINE_PELTON.",
    "init_SOC": "Initial lithium-ion state of charge [-].",
    "min_SOC": "Minimum lithium-ion state of charge [-].",
    "hysteresis_SOC": "SOC hysteresis threshold used by PGMCpp battery dispatch [-].",
    "max_SOC": "Maximum lithium-ion state of charge [-].",
    "charging_efficiency": "Lithium-ion charging efficiency [-].",
    "discharging_efficiency": "Lithium-ion discharging efficiency [-].",
    "replace_SOH": "Battery state-of-health replacement threshold [-].",
    "power_degradation_flag": "Enable/disable battery power degradation logic.",
    "degradation_alpha": "Lithium-ion degradation parameter alpha.",
    "degradation_beta": "Lithium-ion degradation parameter beta.",
    "degradation_B_hat_cal_0": "Lithium-ion calendar degradation parameter.",
    "degradation_r_cal": "Lithium-ion calendar degradation parameter.",
    "degradation_Ea_cal_0": "Lithium-ion calendar degradation activation-energy parameter.",
    "degradation_a_cal": "Lithium-ion calendar degradation parameter.",
    "degradation_s_cal": "Lithium-ion calendar degradation parameter.",
    "gas_constant_JmolK": "Gas constant used in the lithium-ion degradation model [J/(mol*K)].",
}


def help_for(column_name):
    return HELP_TEXT.get(column_name, "PGMCpp input field.")


def text_col(column_name):
    return st.column_config.TextColumn(column_name, help=help_for(column_name))


def number_col(column_name):
    return st.column_config.NumberColumn(column_name, help=help_for(column_name))


def checkbox_col(column_name):
    return st.column_config.CheckboxColumn(column_name, help=help_for(column_name))


def select_col(column_name, options):
    return st.column_config.SelectboxColumn(column_name, options=options, help=help_for(column_name))


def default_column_config(columns):
    cfg = {}

    for col in columns:
        if col == "enabled" or col == "is_sunk" or col == "print_flag" or col == "power_degradation_flag":
            cfg[col] = checkbox_col(col)
        elif col in ["path", "resource_label", "path_2_normalized_production_time_series", "path_2_normalized_performance_matrix"]:
            cfg[col] = text_col(col)
        elif col in ["cost_mode", "type", "power_model", "turbine_type", "capital_cost_basis"]:
            # Specific options are assigned by each table below.
            cfg[col] = text_col(col)
        else:
            cfg[col] = number_col(col)

    return cfg


# ============================================================
# UI setup
# ============================================================

st.set_page_config(page_title="PGMCpp input GUI", layout="wide")
st.title("PGMCpp input GUI")

case_file_text = st.text_input("Case TOML file", value=str(DEFAULT_CASE_FILE))
case_file = Path(case_file_text).expanduser().resolve()

# Keep the editable TOML document in Streamlit session state.
# This prevents unsaved edits from being lost when buttons trigger reruns.
if (
    "active_case_file" not in st.session_state
    or st.session_state["active_case_file"] != str(case_file)
    or "cfg" not in st.session_state
):
    st.session_state["active_case_file"] = str(case_file)
    st.session_state["cfg"] = load_toml(case_file)

cfg = st.session_state["cfg"]

ensure_section(cfg, "paths")
ensure_section(cfg, "model")
ensure_section(cfg, "economics")
ensure_section(cfg, "output")

for section in [
    "renewable_resources",
    "diesel_generators",
    "wind_assets",
    "solar_assets",
    "tidal_assets",
    "wave_assets",
    "hydro_assets",
    "liion_batteries",
]:
    ensure_aot(cfg, section)

cfg = migrate_legacy_renewable_assets(cfg)
cfg = migrate_costs(cfg)
cfg = auto_assign_resource_keys(cfg)

show_advanced = st.toggle("Show advanced columns", value=False)


# ============================================================
# Core settings
# ============================================================

st.header("Core case settings")

col1, col2 = st.columns(2)

with col1:
    cfg["paths"]["pgmcpp_pybindings"] = st.text_input(
        "PGMCpp pybindings path",
        value=str(cfg["paths"].get("pgmcpp_pybindings", "")),
    )

    cfg["paths"]["electrical_load_time_series"] = st.text_input(
        "Electrical load time series",
        value=str(cfg["paths"].get("electrical_load_time_series", "")),
    )

    cfg["output"]["results_name"] = st.text_input(
        "Results name",
        value=str(cfg["output"].get("results_name", "PGMcpp_GUI_case")),
    )

with col2:
    current_mode = str(cfg["model"].get("control_mode", "LOAD_FOLLOWING")).upper()

    if current_mode not in ["LOAD_FOLLOWING", "CYCLE_CHARGING"]:
        current_mode = "LOAD_FOLLOWING"

    cfg["model"]["control_mode"] = st.selectbox(
        "Control mode",
        options=["LOAD_FOLLOWING", "CYCLE_CHARGING"],
        index=["LOAD_FOLLOWING", "CYCLE_CHARGING"].index(current_mode),
    )

    cfg["model"]["firm_dispatch_ratio"] = st.number_input(
        "Firm dispatch ratio [-]",
        value=float(cfg["model"].get("firm_dispatch_ratio", 0.1)),
        step=0.01,
        format="%.4f",
    )

    cfg["model"]["load_reserve_ratio"] = st.number_input(
        "Load reserve ratio [-]",
        value=float(cfg["model"].get("load_reserve_ratio", 0.1)),
        step=0.01,
        format="%.4f",
    )

st.subheader("Cost assumptions")

cfg["economics"]["remote_cost_factor"] = st.number_input(
    "Default remote cost factor [-]",
    value=float(cfg["economics"].get("remote_cost_factor", 1.0)),
    step=0.01,
    format="%.4f",
)

st.caption(
    "All production asset unit costs are CAD/kW. Battery unit costs may be CAD/kWh or CAD/kW."
)


# ============================================================
# Resource files
# ============================================================

st.header("Resource files")

st.caption("Rows are added only with the buttons below. The table itself is fixed-row to avoid accidental row creation while scrolling.")

resource_button_cols = st.columns(len(RESOURCE_TYPES))
for button_col, resource_type in zip(resource_button_cols, RESOURCE_TYPES):
    with button_col:
        if st.button(f"Add {resource_type.lower()} resource", key=f"add_resource_{resource_type}"):
            add_row_and_reload("renewable_resources", resource_defaults(cfg, resource_type))

resource_df = aot_to_df(cfg, "renewable_resources", RESOURCE_BASIC)

resource_df = st.data_editor(
    resource_df,
    num_rows="fixed",
    use_container_width=True,
    key="resource_editor",
    column_config={
        **default_column_config(RESOURCE_BASIC),
        "type": select_col("type", RESOURCE_TYPES),
    },
)

cfg["renewable_resources"] = df_to_aot_preserve(
    resource_df,
    cfg.get("renewable_resources", []),
    RESOURCE_BASIC,
)

cfg = auto_assign_resource_keys(cfg)

with st.expander("Auto-assigned resource keys", expanded=False):
    key_rows = [
        {
            "key": item.get("key"),
            "type": item.get("type"),
            "resource_label": item.get("resource_label"),
            "path": item.get("path"),
        }
        for item in cfg.get("renewable_resources", [])
    ]
    st.dataframe(pd.DataFrame(key_rows), use_container_width=True, hide_index=True)


# ============================================================
# Section table helper
# ============================================================

def render_asset_table(
    title,
    section,
    columns,
    resource_type=None,
    cost_table=False,
    is_battery=False,
    extra_config=None,
    add_defaults=None,
    add_button_label=None,
):
    st.header(title)

    if add_defaults is not None:
        button_label = add_button_label or f"Add {title.lower()} row"
        if st.button(button_label, key=f"add_{section}"):
            add_row_and_reload(section, add_defaults)

    df = aot_to_df(cfg, section, columns)

    col_config = default_column_config(columns)
    col_config["cost_mode"] = select_col("cost_mode", COST_MODES)

    if resource_type is not None:
        col_config["resource_label"] = select_col(
            "resource_label",
            resource_options(cfg, resource_type),
        )

    if is_battery:
        col_config["capital_cost_basis"] = select_col(
            "capital_cost_basis",
            BATTERY_COST_BASES,
        )

    if extra_config:
        col_config.update(extra_config)

    df = st.data_editor(
        df,
        num_rows="fixed",
        use_container_width=True,
        key=f"{section}_{show_advanced}",
        column_config=col_config,
    )

    cfg[section] = df_to_aot_preserve(
        df,
        cfg.get(section, []),
        columns,
        cost_table=cost_table,
        is_battery=is_battery,
    )


# ============================================================
# Generators and assets
# ============================================================

diesel_columns = DIESEL_BASIC + (DIESEL_ADVANCED if show_advanced else [])
render_asset_table(
    "Diesel generators",
    "diesel_generators",
    diesel_columns,
    add_defaults=diesel_defaults(),
    add_button_label="Add diesel generator",
)

wind_columns = PRODUCTION_COST_BASIC + (WIND_ADVANCED if show_advanced else [])
render_asset_table(
    "Wind assets",
    "wind_assets",
    wind_columns,
    resource_type="WIND",
    cost_table=True,
    add_defaults=production_asset_defaults(cfg, "WIND"),
    add_button_label="Add wind asset",
    extra_config={
        "power_model": select_col(
            "power_model",
            ["CUBIC", "EXPONENTIAL", "LOOKUP"],
        )
    },
)

solar_columns = PRODUCTION_COST_BASIC + (SOLAR_ADVANCED if show_advanced else [])
render_asset_table(
    "Solar assets",
    "solar_assets",
    solar_columns,
    resource_type="SOLAR",
    cost_table=True,
    add_defaults=production_asset_defaults(cfg, "SOLAR"),
    add_button_label="Add solar asset",
    extra_config={
        "power_model": select_col(
            "power_model",
            ["SIMPLE", "DETAILED"],
        )
    },
)

tidal_columns = PRODUCTION_COST_BASIC + (TIDAL_ADVANCED if show_advanced else [])
render_asset_table(
    "Tidal assets",
    "tidal_assets",
    tidal_columns,
    resource_type="TIDAL",
    cost_table=True,
    add_defaults=production_asset_defaults(cfg, "TIDAL"),
    add_button_label="Add tidal asset",
    extra_config={
        "power_model": select_col(
            "power_model",
            ["CUBIC", "EXPONENTIAL", "LOOKUP"],
        )
    },
)

wave_columns = PRODUCTION_COST_BASIC + (WAVE_ADVANCED if show_advanced else [])
render_asset_table(
    "Wave assets",
    "wave_assets",
    wave_columns,
    resource_type="WAVE",
    cost_table=True,
    add_defaults=production_asset_defaults(cfg, "WAVE"),
    add_button_label="Add wave asset",
    extra_config={
        "power_model": select_col(
            "power_model",
            ["GAUSSIAN", "PARABOLOID", "LOOKUP"],
        )
    },
)

hydro_columns = PRODUCTION_COST_BASIC + (HYDRO_ADVANCED if show_advanced else [])
render_asset_table(
    "Hydro assets",
    "hydro_assets",
    hydro_columns,
    resource_type="HYDRO",
    cost_table=True,
    add_defaults=production_asset_defaults(cfg, "HYDRO"),
    add_button_label="Add hydro asset",
    extra_config={
        "turbine_type": select_col(
            "turbine_type",
            ["PELTON", "FRANCIS", "KAPLAN"],
        )
    },
)

liion_columns = LIION_BASIC + (LIION_ADVANCED if show_advanced else [])
render_asset_table(
    "Lithium-ion batteries",
    "liion_batteries",
    liion_columns,
    cost_table=True,
    is_battery=True,
    add_defaults=liion_defaults(),
    add_button_label="Add lithium-ion battery",
)

cfg = auto_assign_resource_keys(cfg)


# ============================================================
# Actions
# ============================================================

st.header("Actions")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Save TOML", type="primary"):
        save_toml(case_file, cfg)
        st.success(f"Saved: {case_file}")

with col2:
    runner_path = SCRIPT_DIR / "full_gui_project.py"
    dashboard_path = SCRIPT_DIR / "dashboard.py"

    if st.button("Save, run PGMCpp, then open dashboard"):
        save_toml(case_file, cfg)

        if not runner_path.exists():
            st.error(f"Could not find runner: {runner_path}")
        else:
            completed = subprocess.run(
                [sys.executable, str(runner_path), str(case_file)],
                cwd=str(SCRIPT_DIR),
                text=True,
                capture_output=True,
            )

            st.subheader("PGMCpp terminal output")
            st.code(completed.stdout)

            if completed.stderr:
                st.subheader("Errors / warnings")
                st.code(completed.stderr)

            if completed.returncode == 0:
                st.success("PGMCpp run complete.")
                launch_dashboard(dashboard_path, case_file)
            else:
                st.error(f"PGMCpp failed with return code {completed.returncode}. Dashboard was not launched.")

with col3:
    if st.button("Reload from disk"):
        st.session_state.pop("cfg", None)
        st.session_state.pop("active_case_file", None)
        st.rerun()

st.session_state["cfg"] = cfg

with st.expander("Raw TOML preview", expanded=False):
    st.code(tomlkit.dumps(cfg), language="toml")
