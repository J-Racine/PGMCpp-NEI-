"""
Dashboard for PRIMED Grid Modelling / PGMcpp results.

Main fixes relative to the original:
1. Does not blindly delete renewable CSV columns.
2. Removes only unnamed CSV index columns.
3. Uses full-resolution plotting so hourly wind spikes are preserved.
4. Adds a visible dashboard version stamp to verify the edited file is running.
5. Runs on a fixed non-debug port to avoid stale Dash reloader processes.
6. Opens a completed PGMcpp results folder directly; no TOML file is required.
"""

# ============================================================
# Imports
# ============================================================

import os
import re
import sys
from pathlib import Path

import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.express as px
import plotly.graph_objects as go

# ============================================================
# User inputs / direct results folder handling
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_RESULTS_FOLDER = Path(
    r"C:\Users\jracine\Desktop\PGMcpp_NEI_version\projects\results\paulatuk_single_case\growth_08_PATH_02"
)

start_year = 2026

# Downsampling is disabled. Keep this only as a future option.
MAX_PLOT_POINTS = None


def validate_results_folder(results_folder):
    """
    Use a completed PGMcpp results folder directly.

    Expected structure:
        results_folder/
            Model/
                time_series_results.csv
            Production/
            Storage/
    """
    results_folder = Path(results_folder).expanduser().resolve()

    model_csv = results_folder / "Model" / "time_series_results.csv"

    if not model_csv.exists():
        raise FileNotFoundError(
            "Dashboard could not find the PGMcpp output CSV.\n\n"
            f"Results folder checked: {results_folder}\n"
            f"Expected CSV: {model_csv}"
        )

    return results_folder


def get_results_folder_from_command_line():
    """
    Launch forms:
        python dashboard.py

    or:
        python dashboard.py "C:\\Users\\jracine\\Desktop\\PGMcpp_NEI_version\\projects\\results\\paulatuk_single_case\\growth_08_PATH_02"
    """
    if len(sys.argv) > 2:
        raise ValueError("Usage: python dashboard.py [results_folder]")

    if len(sys.argv) == 2:
        results_folder = Path(sys.argv[1])
    else:
        results_folder = DEFAULT_RESULTS_FOLDER

    return validate_results_folder(results_folder)


main_folder_path = str(get_results_folder_from_command_line())


# ============================================================
# Runtime verification
# ============================================================

DASHBOARD_VERSION = "PGMCPP_DASHBOARD_DIRECT_RESULTS_FOLDER"


# ============================================================
# Paths
# ============================================================

sub_folder_path_model = os.path.join(main_folder_path, "Model")
sub_folder_path_combustion = os.path.join(main_folder_path, "Production", "Combustion")
sub_folder_path_noncombustion = os.path.join(main_folder_path, "Production", "Noncombustion")
sub_folder_path_renewable = os.path.join(main_folder_path, "Production", "Renewable")
sub_folder_path_storage = os.path.join(main_folder_path, "Storage")


# ============================================================
# Expected columns
# ============================================================

RAW_TIME_COL = "Time (since start of data) [hrs]"
HOURS_PER_YEAR = 8760.0
PLOT_HOUR_COL = "plot_hour"

cols_energy = [
    RAW_TIME_COL,
    "datetime",
    "timestep",
    "Production [kW]",
    "Dispatch [kW]",
    "Storage [kW]",
    "Curtailment [kW]",
]

cols_storage_preferred = [
    "datetime",
    "Charging Power [kW]",
    "Discharging Power [kW]",
    "Charge (at end of timestep) [kWh]",
    "State of Health (at end of timestep) [ ]",
]


# ============================================================
# Helpers
# ============================================================

def clean_csv_dataframe(csv_file_path):
    """
    Read a CSV and remove only unnamed index columns.
    This avoids deleting real data columns.
    """
    df = pd.read_csv(csv_file_path)

    unnamed_cols = [col for col in df.columns if str(col).startswith("Unnamed")]
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)

    return df


def safe_select_columns(df, wanted_cols, label):
    """
    Select wanted columns if present.
    Raise a useful error if a required column is missing.
    """
    missing = [col for col in wanted_cols if col not in df.columns]
    if missing:
        raise KeyError(
            f"{label}: missing columns {missing}. Available columns: {df.columns.tolist()}"
        )

    return df[wanted_cols]


def read_text_file(file_path):
    if not os.path.exists(file_path):
        return ""

    with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
        return file.read()


def extract_float(pattern, text, default=0.0):
    match = re.search(pattern, text)
    if not match:
        return default

    try:
        return float(match.group(1))
    except ValueError:
        return default


def extract_section(pattern, text, default_text):
    if hasattr(pattern, "search"):
        match = pattern.search(text)
    else:
        match = re.search(pattern, text, re.DOTALL)

    if not match:
        return default_text

    return match.group(1).strip()


def make_markdown_card(text, width="80%"):
    return html.Div(
        [
            dcc.Markdown(
                text,
                style={
                    "width": width,
                    "margin": "auto",
                    "border": "1px solid #ddd",
                    "padding": "10px",
                    "whiteSpace": "pre-wrap",
                },
                dangerously_allow_html=True,
            )
        ],
        style={"width": "100%", "textAlign": "left", "padding": "20px"},
    )


def make_section_title(text):
    return html.Div(
        [
            dcc.Markdown(
                f"**{text}**",
                style={
                    "fontSize": "1.5em",
                    "color": "blue",
                    "width": "80%",
                    "margin": "auto",
                    "marginBottom": "1px",
                    "fontWeight": "bold",
                },
            )
        ],
        style={"width": "100%", "textAlign": "left", "padding": "1px"},
    )


def markdown_items_from_dict(data_dict):
    children = []

    for name, text in data_dict.items():
        children.append(
            html.Div(
                [
                    dcc.Markdown(
                        f"### **{name}**\n\n{text.replace('## ', '#### ')}",
                        style={
                            "width": "80%",
                            "margin": "auto",
                            "textAlign": "left",
                            "border": "1px solid #ddd",
                            "padding": "10px",
                            "whiteSpace": "pre-wrap",
                        },
                        dangerously_allow_html=True,
                    )
                ],
                style={"width": "100%", "textAlign": "left", "padding": "20px"},
            )
        )

    return children


def make_dash_table(df):
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": col, "id": col} for col in df.columns],
        style_table={
            "width": "80%",
            "margin": "auto",
            "overflowX": "auto",
            "border": "1px solid #ddd",
        },
        style_cell={
            "textAlign": "center",
            "padding": "8px",
            "border": "1px solid #ddd",
        },
        style_header={
            "fontWeight": "bold",
            "backgroundColor": "#f2f2f2",
        },
    )


def non_plot_columns():
    return ["datetime", "timestep", RAW_TIME_COL, PLOT_HOUR_COL]


def get_y_axis_columns(df):
    return [col for col in df.columns if col not in non_plot_columns()]


def choose_x_axis(df):
    """
    Prefer local hour within the selected year.
    This keeps the slider as 0 to 8760 h and avoids row-index errors for minute data.
    """
    if PLOT_HOUR_COL in df.columns:
        return PLOT_HOUR_COL
    if RAW_TIME_COL in df.columns:
        return RAW_TIME_COL
    if "timestep" in df.columns:
        return "timestep"
    return "datetime"


def downsample_for_plot(df, max_points=MAX_PLOT_POINTS):
    """
    Downsampling disabled.
    Full hourly data is plotted so intermittent wind spikes are preserved.
    """
    return df


def plot_timeseries(df, x_col, y_cols, title, legend_title):
    """
    Exact raw line plot.

    Uses the raw row/time order and does not downsample.
    This is intentionally closer to Excel than to a smoothed dashboard plot.
    """
    if isinstance(y_cols, str):
        y_cols = [y_cols]

    if not y_cols:
        y_cols = get_y_axis_columns(df)

    x_label = "Hour of selected year [h]" if x_col == PLOT_HOUR_COL else ("Elapsed time [h]" if x_col == RAW_TIME_COL else "Time")

    fig = go.Figure()

    for y_col in y_cols:
        if y_col not in df.columns:
            continue

        fig.add_trace(
            go.Scattergl(
                x=df[x_col],
                y=pd.to_numeric(df[y_col], errors="coerce"),
                mode="lines",
                name=y_col,
                connectgaps=False,
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title="Value",
        legend_title=legend_title,
        hovermode="x unified",
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
    )

    return fig


def get_year_window(df, selected_year, selected_x_range):
    """
    Slices by actual PGMcpp elapsed time in hours, not by row index.

    This fixes 1-minute data:
        8760 rows = 146 hours, not 1 year.

    Slider values remain in hours:
        [0, 8760] = full selected year.
    """
    left_hour = float(selected_x_range[0])
    right_hour = float(selected_x_range[1])

    raw_hours = raw_hours_series(df)

    if raw_hours is not None and raw_hours.notna().any():
        absolute_left = selected_year * HOURS_PER_YEAR + left_hour
        absolute_right = selected_year * HOURS_PER_YEAR + right_hour

        mask = (raw_hours >= absolute_left) & (raw_hours <= absolute_right)

        filtered_df = df.loc[mask, :].copy()
        filtered_df[PLOT_HOUR_COL] = raw_hours.loc[mask].to_numpy() - selected_year * HOURS_PER_YEAR

        pass

        return filtered_df

    # Fallback for files without raw time column: preserve old hourly-row behavior.
    start = selected_year * 8760
    stop = (selected_year + 1) * 8760

    year_df = df.iloc[start:stop, :]

    left = int(selected_x_range[0])
    right = int(selected_x_range[1]) + 1

    filtered_df = year_df.iloc[left:right, :].copy()
    filtered_df[PLOT_HOUR_COL] = range(len(filtered_df))

    return filtered_df


def get_existing_subfolders(path):
    if not os.path.isdir(path):
        return []

    return [
        folder for folder in os.listdir(path)
        if os.path.isdir(os.path.join(path, folder))
    ]


def read_asset_markdown_sections(asset_root, specs_pattern, results_pattern):
    specs = {}
    results = {}

    if not os.path.isdir(asset_root):
        return specs, results

    for folder in get_existing_subfolders(asset_root):
        md_path = os.path.join(asset_root, folder, "summary_results.md")

        if not os.path.exists(md_path):
            continue

        text = read_text_file(md_path)

        specs[folder] = extract_section(
            specs_pattern,
            text,
            "No Specs Found!",
        )

        results[folder] = extract_section(
            results_pattern,
            text,
            "No Results Found!",
        )

    return specs, results


def find_storage_soh_column(df):
    """
    Handles spelling differences in PGMcpp storage output.
    """
    candidates = [
        "State of Health (at end of timestep) [ ]",
        "Sate of Health (at end of timestep) []",
        "State of Health (at end of timestep) []",
        "Sate of Health (at end of timestep) [ ]",
    ]

    for col in candidates:
        if col in df.columns:
            return col

    return None



def raw_hours_series(df):
    """
    Returns numeric raw PGMcpp time in hours if available.
    """
    if RAW_TIME_COL not in df.columns:
        return None

    return pd.to_numeric(df[RAW_TIME_COL], errors="coerce")


def add_datetime_and_timestep(df, fallback_times=None):
    """
    Adds datetime and timestep columns without assuming hourly resolution.

    If the raw PGMcpp time column exists, datetime is created from actual elapsed hours.
    If not, fallback_times is used.
    """
    df = df.copy()
    df["timestep"] = range(len(df))

    raw_hours = raw_hours_series(df)

    if raw_hours is not None and raw_hours.notna().any():
        start_datetime = pd.Timestamp(f"{start_year}-01-01 00:00:00")
        df["datetime"] = start_datetime + pd.to_timedelta(raw_hours.fillna(0), unit="h")
    elif fallback_times is not None:
        df["datetime"] = fallback_times.iloc[:len(df)].reset_index(drop=True)
    else:
        df["datetime"] = pd.date_range(
            start=f"{start_year}-01-01 00:00:00",
            periods=len(df),
            freq="1h",
        )

    if RAW_TIME_COL not in df.columns:
        df[RAW_TIME_COL] = df["timestep"]

    return df


def infer_n_years_from_raw_time(df):
    """
    Infers project years using actual PGMcpp time, not row count.
    Works for hourly, minute, or other timestep resolutions.
    """
    raw_hours = raw_hours_series(df)

    if raw_hours is not None and raw_hours.notna().any():
        max_hour = float(raw_hours.max())
        return max(1, int(max_hour // HOURS_PER_YEAR) + 1)

    return max(1, round(len(df) / 8760))


def infer_timestep_hours(df):
    """
    Estimates timestep size in hours from the raw PGMcpp time column.
    """
    raw_hours = raw_hours_series(df)

    if raw_hours is None:
        return None

    diffs = raw_hours.diff().dropna()
    diffs = diffs[diffs > 0]

    if len(diffs) == 0:
        return None

    return float(diffs.median())



# ============================================================
# Read model time-series
# ============================================================

model_csv_path = os.path.join(sub_folder_path_model, "time_series_results.csv")

if not os.path.exists(model_csv_path):
    raise FileNotFoundError(f"Model CSV not found: {model_csv_path}")

dataframes_model_main = {}
dataframes_combustion = {}
dataframes_combustion_status = {}
dataframes_noncombustion = {}
dataframes_renewable = {}
dataframes_storage = {}

model_df = clean_csv_dataframe(model_csv_path)

# Build datetime vector based on actual PGMcpp elapsed time.
# This supports 1-minute, hourly, or other timestep resolutions.
model_df = add_datetime_and_timestep(model_df)

n_rows = len(model_df)
n_years = infer_n_years_from_raw_time(model_df)
timestep_hours = infer_timestep_hours(model_df)

pass
pass
pass
pass

# Drop Net Load from the model plot if it exists, matching the original dashboard behavior.
if "Net Load [kW]" in model_df.columns:
    model_df_for_plot = model_df.drop(columns=["Net Load [kW]"])
else:
    model_df_for_plot = model_df.copy()

dataframes_model_main["Model"] = model_df_for_plot


# ============================================================
# Read asset CSVs
# ============================================================

folder_paths = [
    sub_folder_path_combustion,
    sub_folder_path_noncombustion,
    sub_folder_path_renewable,
    sub_folder_path_storage,
]

for path in folder_paths:
    if not os.path.isdir(path):
        pass
        continue

    for folder in get_existing_subfolders(path):
        folder_path = os.path.join(path, folder)
        csv_file_path = os.path.join(folder_path, "time_series_results.csv")

        if not os.path.exists(csv_file_path):
            pass
            continue

        try:
            df = clean_csv_dataframe(csv_file_path)

            df = add_datetime_and_timestep(df)

            pass
            pass

            if "Production [kW]" in df.columns:
                prod = pd.to_numeric(df["Production [kW]"], errors="coerce")
                pass

            if path == sub_folder_path_combustion:
                dataframes_combustion[folder] = safe_select_columns(
                    df,
                    cols_energy,
                    f"Combustion asset {folder}",
                )

                if "Is Running (N = 0 / Y = 1)" in df.columns:
                    dataframes_combustion_status[folder] = df[["Is Running (N = 0 / Y = 1)"]]
                else:
                    pass

            elif path == sub_folder_path_noncombustion:
                dataframes_noncombustion[folder] = safe_select_columns(
                    df,
                    cols_energy,
                    f"Noncombustion asset {folder}",
                )

            elif path == sub_folder_path_renewable:
                # Important: do NOT drop df.columns[1].
                dataframes_renewable[folder] = safe_select_columns(
                    df,
                    cols_energy,
                    f"Renewable asset {folder}",
                )

            elif path == sub_folder_path_storage:
                dataframes_storage[folder] = df

        except Exception as e:
            pass
            pass


col_time = "timestep"


# ============================================================
# Operation mode analysis
# ============================================================

operation_df = pd.DataFrame(index=dataframes_model_main["Model"].index)
operation_df["datetime"] = dataframes_model_main["Model"]["datetime"]
operation_df["timestep"] = dataframes_model_main["Model"]["timestep"]

if dataframes_combustion_status:
    df_combustion_status = pd.concat(
        [df for df in dataframes_combustion_status.values()],
        axis=1,
    )

    df_combustion_status["Total"] = df_combustion_status.sum(axis=1)

    operation_df["Diesel On Mode"] = df_combustion_status["Total"].apply(
        lambda x: 1 if x > 0 else 0
    )

    operation_df["Diesel Off Mode"] = df_combustion_status["Total"].apply(
        lambda x: 1 if x == 0 else 0
    )

else:
    operation_df["Diesel On Mode"] = 0
    operation_df["Diesel Off Mode"] = 0

dataframes_model_main["Operation_Mode"] = operation_df

df_operation_modes = operation_df.drop(columns=["datetime", "timestep"]).groupby(
    operation_df.index // 8760
).sum()

df_operation_modes.insert(0, "Year", df_operation_modes.index + 1)

df_operation_modes.columns = [
    "Year",
    "Diesel On Mode (h)",
    "Diesel Off Mode (h)",
]

total_mode_hours = (
    df_operation_modes["Diesel On Mode (h)"]
    + df_operation_modes["Diesel Off Mode (h)"]
)

df_operation_modes["Diesel On Mode (%)"] = (
    100 * df_operation_modes["Diesel On Mode (h)"] / total_mode_hours
).fillna(0).round(2)

df_operation_modes["Diesel Off Mode (%)"] = (
    100 * df_operation_modes["Diesel Off Mode (h)"] / total_mode_hours
).fillna(0).round(2)


# ============================================================
# Read summary markdown
# ============================================================

file_path_model_summary = os.path.join(sub_folder_path_model, "summary_results.md")
file_contents_model_summary = read_text_file(file_path_model_summary)

project_lifetime = round(
    extract_float(r"Years: (\S+)", file_contents_model_summary, default=float(n_years)),
    1,
)

total_net_present_cost = extract_float(
    r"Net Present Cost: (\S+)",
    file_contents_model_summary,
)

total_LCOE = round(
    extract_float(
        r"Levellized Cost of Energy: (\S+)",
        file_contents_model_summary,
    ),
    4,
)

total_renewable_fraction = round(
    100 * extract_float(
        r"Renewable Penetration: (\S+)",
        file_contents_model_summary,
    ),
    2,
)

total_dispatch_and_discharge = extract_float(
    r" Discharge: (\S+)",
    file_contents_model_summary,
)

total_fuel_consumed = extract_float(
    r"Total Fuel Consumed: (\S+)",
    file_contents_model_summary,
)

model_summary = extract_section(
    r"# Model Summary Results(.*?)## Results",
    file_contents_model_summary,
    "No Model Summary!",
)

results_summary_model = extract_section(
    r"## Results(.*?)Total Carbon Dioxide",
    file_contents_model_summary,
    "No Results Summary!",
)

emission_summary_model_match = re.search(
    r"Total Carbon Dioxide.*?(?=\n\n|\Z)",
    file_contents_model_summary,
    re.DOTALL,
)

if emission_summary_model_match:
    emission_summary_model = emission_summary_model_match.group().strip()
else:
    emission_summary_model = "No Emission Results!"


# ============================================================
# Read asset markdown summaries
# ============================================================

specs_pattern = re.compile(r"-------(.*?)## Results", re.DOTALL)
results_pattern_combustion = re.compile(r"## Results(.*?)Total Carbon Dioxide", re.DOTALL)
results_pattern_general = re.compile(r"## Results(.*?)-----", re.DOTALL)

specs_summary_combustion, results_summary_combustion = read_asset_markdown_sections(
    sub_folder_path_combustion,
    specs_pattern,
    results_pattern_combustion,
)

specs_summary_noncombustion, results_summary_noncombustion = read_asset_markdown_sections(
    sub_folder_path_noncombustion,
    specs_pattern,
    results_pattern_general,
)

specs_summary_renewable, results_summary_renewable = read_asset_markdown_sections(
    sub_folder_path_renewable,
    specs_pattern,
    results_pattern_general,
)

specs_summary_storage, results_summary_storage = read_asset_markdown_sections(
    sub_folder_path_storage,
    specs_pattern,
    results_pattern_general,
)

emission_summary_combustion = {}

if os.path.isdir(sub_folder_path_combustion):
    for folder in get_existing_subfolders(sub_folder_path_combustion):
        md_path = os.path.join(sub_folder_path_combustion, folder, "summary_results.md")
        text = read_text_file(md_path)

        match = re.search(r"Total Carbon Dioxide.*?(?=\n\n|\Z)", text, re.DOTALL)

        if match:
            emission_summary_combustion[folder] = match.group().strip()
        else:
            emission_summary_combustion[folder] = "No Results Found!"


# ============================================================
# Build tabs
# ============================================================

children_tab_1 = [
    dcc.Tab(
        label="Model Summary",
        value="tab-1",
        children=[
            html.Div(
                [
                    dcc.Markdown(
                        "**The overall model configuration is as follows:**",
                        style={
                            "fontSize": "1.2em",
                            "width": "95%",
                            "margin": "auto",
                            "fontWeight": "bold",
                        },
                    )
                ],
                style={"width": "100%", "textAlign": "left", "padding": "1px"},
            ),
            make_markdown_card(model_summary.replace("## ", "### ")),
        ],
    )
]

children_tab_2 = [
    dcc.Tab(
        label="Model Details",
        value="tab-2",
        children=[
            html.Div(
                [
                    dcc.Markdown(
                        "**The specifications of all assets are as follows:**",
                        style={
                            "fontSize": "1.2em",
                            "width": "95%",
                            "margin": "auto",
                            "fontWeight": "bold",
                        },
                    )
                ],
                style={"width": "100%", "textAlign": "left", "padding": "1px"},
            ),
            make_section_title("Combustion Assets Specifications"),
            *markdown_items_from_dict(specs_summary_combustion),
            make_section_title("Noncombustion Assets Specifications"),
            *markdown_items_from_dict(specs_summary_noncombustion),
            make_section_title("Renewable Assets Specifications"),
            *markdown_items_from_dict(specs_summary_renewable),
            make_section_title("Storage Assets Specifications"),
            *markdown_items_from_dict(specs_summary_storage),
        ],
    )
]

children_tab_3 = [
    dcc.Tab(
        label="Results Summary",
        value="tab-3",
        children=[
            make_section_title("System Level Results"),
            make_markdown_card(results_summary_model),
            make_section_title("Combustion Assets Results"),
            *markdown_items_from_dict(results_summary_combustion),
            make_section_title("Noncombustion Assets Results"),
            *markdown_items_from_dict(results_summary_noncombustion),
            make_section_title("Renewable Assets Results"),
            *markdown_items_from_dict(results_summary_renewable),
            make_section_title("Storage Assets Results"),
            *markdown_items_from_dict(results_summary_storage),
            make_section_title("Operation Modes"),
            html.Div(
                [
                    make_dash_table(
                        df_operation_modes[
                            [
                                "Year",
                                "Diesel On Mode (h)",
                                "Diesel Off Mode (h)",
                                "Diesel On Mode (%)",
                                "Diesel Off Mode (%)",
                            ]
                        ]
                    )
                ],
                style={"padding": "20px"},
            ),
        ],
    )
]

children_tab_4 = [
    dcc.Tab(
        label="Overall Dispatch",
        value="tab-4",
        children=[
            html.Div(
                [
                    dcc.Markdown(
                        "Slider:",
                        style={
                            "fontSize": "1.2em",
                            "width": "95%",
                            "margin": "auto",
                        },
                    )
                ],
                style={"width": "100%", "textAlign": "left", "padding": "1px"},
            ),
            dcc.RangeSlider(
                id="x-axis-slider",
                min=0,
                max=8760,
                step=1,
                marks={i: str(i) for i in range(0, 8761, 500)},
                value=[0, 8760],
                allowCross=True,
            ),
            dcc.Graph(id="model-line-plot-1", style={"height": "70vh"}),
            dcc.Graph(id="model-line-plot-2", style={"height": "40vh"}),
        ],
    )
]

if dataframes_combustion:
    first_combustion_df = next(iter(dataframes_combustion.values()))
    combustion_default = get_y_axis_columns(first_combustion_df)[0]

    children_tab_5 = [
        dcc.Tab(
            label="Combustions",
            value="tab-5",
            children=[
                dcc.Dropdown(
                    id="column-selector-combustion-plot",
                    options=[
                        {"label": col, "value": col}
                        for col in get_y_axis_columns(first_combustion_df)
                    ],
                    multi=True,
                    value=[combustion_default],
                    style={"width": "48%", "marginBottom": "20px"},
                ),
                *[
                    dcc.Graph(id=f"combustion-line-plot-{i}")
                    for i in range(len(dataframes_combustion))
                ],
            ],
        )
    ]
else:
    children_tab_5 = []

if dataframes_noncombustion:
    first_noncombustion_df = next(iter(dataframes_noncombustion.values()))
    noncombustion_default = get_y_axis_columns(first_noncombustion_df)[0]

    children_tab_6 = [
        dcc.Tab(
            label="Noncombustions",
            value="tab-6",
            children=[
                dcc.Dropdown(
                    id="column-selector-noncombustion-plot",
                    options=[
                        {"label": col, "value": col}
                        for col in get_y_axis_columns(first_noncombustion_df)
                    ],
                    multi=True,
                    value=[noncombustion_default],
                    style={"width": "48%", "marginBottom": "20px"},
                ),
                *[
                    dcc.Graph(id=f"noncombustion-line-plot-{i}")
                    for i in range(len(dataframes_noncombustion))
                ],
            ],
        )
    ]
else:
    children_tab_6 = []

if dataframes_renewable:
    first_renewable_df = next(iter(dataframes_renewable.values()))
    renewable_default = get_y_axis_columns(first_renewable_df)[0]

    children_tab_7 = [
        dcc.Tab(
            label="Renewables",
            value="tab-7",
            children=[
                dcc.Dropdown(
                    id="column-selector-renewable-plot",
                    options=[
                        {"label": col, "value": col}
                        for col in get_y_axis_columns(first_renewable_df)
                    ],
                    multi=True,
                    value=[renewable_default],
                    style={"width": "48%", "marginBottom": "20px"},
                ),
                *[
                    dcc.Graph(id=f"renewable-line-plot-{i}")
                    for i in range(len(dataframes_renewable))
                ],
            ],
        )
    ]
else:
    children_tab_7 = []

if dataframes_storage:
    first_storage_df = next(iter(dataframes_storage.values()))

    storage_plot_cols = [
        col for col in [
            "Charging Power [kW]",
            "Discharging Power [kW]",
            "Charge (at end of timestep) [kWh]",
        ]
        if col in first_storage_df.columns
    ]

    if not storage_plot_cols:
        storage_plot_cols = [
            col for col in first_storage_df.columns
            if col not in non_plot_columns()
        ][:3]

    children_tab_8 = [
        dcc.Tab(
            label="Storages",
            value="tab-8",
            children=[
                dcc.Dropdown(
                    id="column-selector-storage-power-plot",
                    options=[
                        {"label": col, "value": col}
                        for col in storage_plot_cols
                    ],
                    multi=True,
                    value=[storage_plot_cols[0]],
                    style={"width": "48%", "marginBottom": "20px"},
                ),
                *[
                    dcc.Graph(id=f"storage-power-line-plot-{i}")
                    for i in range(len(dataframes_storage))
                ],
                *[
                    dcc.Graph(id=f"storage-health-line-plot-{i}")
                    for i in range(len(dataframes_storage))
                ],
            ],
        )
    ]
else:
    children_tab_8 = []

children_tab_9 = [
    dcc.Tab(
        label="Emissions",
        value="tab-9",
        children=[
            make_section_title("System Level Emissions"),
            make_markdown_card(emission_summary_model),
            make_section_title("Combustion Assets' Emissions"),
            *markdown_items_from_dict(emission_summary_combustion),
        ],
    )
]

children = (
    children_tab_1
    + children_tab_2
    + children_tab_3
    + children_tab_4
    + children_tab_5
    + children_tab_6
    + children_tab_7
    + children_tab_8
    + children_tab_9
)


# ============================================================
# Initialize app
# ============================================================

app = dash.Dash(__name__)
app.title = "PGMcpp Results"

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div(
                    [
                        html.H1(
                            "PGMcpp Results",
                            style={"fontSize": "2em", "marginBottom": "15px"},
                        ),
                        html.Div(html.Strong("Project Name:"), style={"fontSize": "1em"}),
                        html.Div(f"{main_folder_path}", style={"fontSize": "1em"}),
                    ],
                    style={
                        "backgroundColor": "#101D6B",
                        "padding": "40px",
                        "color": "white",
                        "flex": "50%",
                    },
                ),
                html.Div(
                    [
                        html.Div(html.Strong("System Architecture:"), style={"fontSize": "1em"}),
                        html.Ul(
                            [
                                html.Li(key, style={"marginBottom": "3px"})
                                for dictionary in [
                                    dataframes_combustion,
                                    dataframes_noncombustion,
                                    dataframes_renewable,
                                    dataframes_storage,
                                ]
                                if dictionary
                                for key in dictionary.keys()
                            ],
                            style={"fontSize": "0.9em"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#101D6B",
                        "color": "white",
                        "flex": "30%",
                        "textAlign": "left",
                        "paddingRight": "40px",
                        "paddingTop": "20px",
                    },
                ),
                html.Div(
                    [
                        html.Div(html.Strong("Main Summary:"), style={"fontSize": "1em"}),
                        html.Ul(
                            [
                                html.Li(f"Project Lifetime: {project_lifetime} years"),
                                html.Li(f"Total NPC: {total_net_present_cost:,.2f} $"),
                                html.Li(f"Levelized COE: {total_LCOE} $/kWh"),
                                html.Li(f"Renewable Fraction: {total_renewable_fraction} %"),
                                html.Li(
                                    f"Total Dispatch & Discharge: {total_dispatch_and_discharge:,.2f} kWh"
                                ),
                                html.Li(f"Total Fuel Consumed: {total_fuel_consumed:,.2f} L"),
                            ],
                            style={"fontSize": "0.9em"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#101D6B",
                        "color": "white",
                        "flex": "40%",
                        "textAlign": "left",
                        "paddingRight": "40px",
                        "paddingTop": "20px",
                    },
                ),
                html.Div(
                    [
                        html.Div(
                            html.Strong("Year:"),
                            style={
                                "fontSize": "1em",
                                "color": "white",
                                "marginBottom": "20px",
                            },
                        ),
                        dcc.Dropdown(
                            id="year-dropdown",
                            options=[
                                {"label": f"{i + 1}", "value": i}
                                for i in range(int(max(1, n_years)))
                            ],
                            value=0,
                            style={
                                "width": "100%",
                                "marginBottom": "20px",
                                "color": "black",
                            },
                        ),
                    ],
                    style={
                        "backgroundColor": "#101D6B",
                        "flex": "10%",
                        "textAlign": "left",
                        "paddingRight": "40px",
                        "paddingTop": "20px",
                    },
                ),
            ],
            style={
                "display": "flex",
                "justifyContent": "space-between",
                "fontFamily": "Lato, sans-serif",
            },
        ),
        dcc.Tabs(id="tabs", value="tab-1", children=children),
        html.Div(
            [
                html.H1(
                    "Dashboard Designed for PRIMED Grid Modelling Program",
                    style={"fontSize": "1em", "marginBottom": "20px"},
                )
            ],
            style={
                "backgroundColor": "#101D6B",
                "padding": "10px",
                "color": "white",
            },
        ),
    ]
)


# ============================================================
# Callbacks
# ============================================================

@app.callback(
    Output("model-line-plot-1", "figure"),
    [
        Input("x-axis-slider", "value"),
        Input("year-dropdown", "value"),
    ],
)
def update_model_dispatch_plot(selected_x_range, selected_year):
    filtered_df = get_year_window(
        dataframes_model_main["Model"],
        selected_year,
        selected_x_range,
    )

    y_cols = get_y_axis_columns(filtered_df)

    return plot_timeseries(
        filtered_df,
        x_col=choose_x_axis(filtered_df),
        y_cols=y_cols,
        title="Load & Dispatch",
        legend_title="Legend",
    )


@app.callback(
    Output("model-line-plot-2", "figure"),
    [
        Input("x-axis-slider", "value"),
        Input("year-dropdown", "value"),
    ],
)
def update_operation_mode_plot(selected_x_range, selected_year):
    filtered_df = get_year_window(
        dataframes_model_main["Operation_Mode"],
        selected_year,
        selected_x_range,
    )

    y_cols = ["Diesel On Mode", "Diesel Off Mode"]

    return plot_timeseries(
        filtered_df,
        x_col=choose_x_axis(filtered_df),
        y_cols=y_cols,
        title="Operation Modes",
        legend_title="Legend",
    )


if dataframes_combustion:
    @app.callback(
        [
            Output(f"combustion-line-plot-{i}", "figure")
            for i in range(len(dataframes_combustion))
        ],
        [
            Input("column-selector-combustion-plot", "value"),
            Input("x-axis-slider", "value"),
            Input("year-dropdown", "value"),
        ],
    )
    def update_combustion_plots(selected_columns, selected_x_range, selected_year):
        figs = []

        for i, (name, df) in enumerate(dataframes_combustion.items()):
            filtered_df = get_year_window(df, selected_year, selected_x_range)

            for col in selected_columns:
                if col in filtered_df.columns:
                    series = pd.to_numeric(filtered_df[col], errors="coerce")
                    pass

            figs.append(
                plot_timeseries(
                    filtered_df,
                    x_col=choose_x_axis(filtered_df),
                    y_cols=selected_columns,
                    title=name,
                    legend_title=f"Legend {i + 1}",
                )
            )

        return figs


if dataframes_noncombustion:
    @app.callback(
        [
            Output(f"noncombustion-line-plot-{i}", "figure")
            for i in range(len(dataframes_noncombustion))
        ],
        [
            Input("column-selector-noncombustion-plot", "value"),
            Input("x-axis-slider", "value"),
            Input("year-dropdown", "value"),
        ],
    )
    def update_noncombustion_plots(selected_columns, selected_x_range, selected_year):
        figs = []

        for i, (name, df) in enumerate(dataframes_noncombustion.items()):
            filtered_df = get_year_window(df, selected_year, selected_x_range)

            figs.append(
                plot_timeseries(
                    filtered_df,
                    x_col=choose_x_axis(filtered_df),
                    y_cols=selected_columns,
                    title=name,
                    legend_title=f"Legend {i + 1}",
                )
            )

        return figs


if dataframes_renewable:
    @app.callback(
        [
            Output(f"renewable-line-plot-{i}", "figure")
            for i in range(len(dataframes_renewable))
        ],
        [
            Input("column-selector-renewable-plot", "value"),
            Input("x-axis-slider", "value"),
            Input("year-dropdown", "value"),
        ],
    )
    def update_renewable_plots(selected_columns, selected_x_range, selected_year):
        pass
        figs = []

        for i, (name, df) in enumerate(dataframes_renewable.items()):
            filtered_df = get_year_window(df, selected_year, selected_x_range)

            for col in selected_columns:
                if col in filtered_df.columns:
                    series = pd.to_numeric(filtered_df[col], errors="coerce")
                    pass

            figs.append(
                plot_timeseries(
                    filtered_df,
                    x_col=choose_x_axis(filtered_df),
                    y_cols=selected_columns,
                    title=name,
                    legend_title=f"Legend {i + 1}",
                )
            )

        return figs


if dataframes_storage:
    @app.callback(
        [
            Output(f"storage-power-line-plot-{i}", "figure")
            for i in range(len(dataframes_storage))
        ],
        [
            Input("column-selector-storage-power-plot", "value"),
            Input("x-axis-slider", "value"),
            Input("year-dropdown", "value"),
        ],
    )
    def update_storage_power_plots(selected_columns, selected_x_range, selected_year):
        figs = []

        for i, (name, df) in enumerate(dataframes_storage.items()):
            filtered_df = get_year_window(df, selected_year, selected_x_range)

            figs.append(
                plot_timeseries(
                    filtered_df,
                    x_col=choose_x_axis(filtered_df),
                    y_cols=selected_columns,
                    title=f"{name} - Power / Charge",
                    legend_title=f"Legend {i + 1}",
                )
            )

        return figs


    @app.callback(
        [
            Output(f"storage-health-line-plot-{i}", "figure")
            for i in range(len(dataframes_storage))
        ],
        [
            Input("x-axis-slider", "value"),
            Input("year-dropdown", "value"),
        ],
    )
    def update_storage_health_plots(selected_x_range, selected_year):
        figs = []

        for i, (name, df) in enumerate(dataframes_storage.items()):
            filtered_df = get_year_window(df, selected_year, selected_x_range)

            soh_col = find_storage_soh_column(filtered_df)

            if soh_col is None:
                fig = px.line(title=f"{name} - State of Health column not found")
                fig.update_layout(
                    annotations=[
                        {
                            "text": "State of Health column not found in storage CSV.",
                            "xref": "paper",
                            "yref": "paper",
                            "showarrow": False,
                            "x": 0.5,
                            "y": 0.5,
                        }
                    ]
                )
            else:
                fig = plot_timeseries(
                    filtered_df,
                    x_col=choose_x_axis(filtered_df),
                    y_cols=[soh_col],
                    title=f"{name} - State of Health",
                    legend_title=f"Legend {i + 1}",
                )

            figs.append(fig)

        return figs


# ============================================================
# Run app
# ============================================================

if __name__ == "__main__":
    import logging
    from flask import cli as flask_cli

    url = "http://127.0.0.1:8051"

    print("=" * 80, flush=True)
    print("STARTING DASHBOARD", flush=True)
    print(f"Dashboard version: {DASHBOARD_VERSION}", flush=True)
    print(f"Dashboard Python file: {Path(__file__).resolve()}", flush=True)
    print(f"Results folder input: {main_folder_path}", flush=True)
    print(f"Results folder: {main_folder_path}", flush=True)
    print(f"Model summary file: {file_path_model_summary}", flush=True)
    print(f"Parsed NPC: {total_net_present_cost}", flush=True)
    print(f"Parsed LCOE: {total_LCOE}", flush=True)
    print(f"Parsed renewable fraction [%]: {total_renewable_fraction}", flush=True)
    print(f"Parsed fuel consumed [L]: {total_fuel_consumed}", flush=True)
    print(url, flush=True)
    print("=" * 80, flush=True)

    logging.getLogger("werkzeug").disabled = False
    logging.getLogger("dash").disabled = False
    logging.getLogger("flask").disabled = False
    flask_cli.show_server_banner = lambda *args, **kwargs: None

    app.run(
        host="127.0.0.1",
        port=8051,
        debug=False,
        use_reloader=False,
    )