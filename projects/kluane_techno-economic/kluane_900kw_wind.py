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

import os
import sys

# ------------------------------------------------------------
# Load local PGMcpp Python bindings
# ------------------------------------------------------------

sys.path.insert(0, r"C:\PGMcpp_work\PGMcpp\pybindings")

import PGMcpp

print("PGMcpp loaded from:", PGMcpp.__file__)


# ============================================================
# User-defined economic assumptions
# ============================================================

REMOTE_COST_FACTOR = 3.24
USD_TO_CAD_FACTOR = 1.39

DIESEL_FUEL_COST_CAD_PER_L = 2.699

WIND_UNIT_COST_USD_PER_KW = 2256.06
LIION_UNIT_COST_USD_PER_KWH = 1869.714

WIND_UNIT_COST_CAD_PER_KW = WIND_UNIT_COST_USD_PER_KW * USD_TO_CAD_FACTOR
LIION_UNIT_COST_CAD_PER_KWH = LIION_UNIT_COST_USD_PER_KWH * USD_TO_CAD_FACTOR


# ============================================================
# Load time-series data
# ============================================================

path_2_electrical_load_time_series = (
    r"C:\PGMcpp_work\PGMcpp\data\test\electrical_load\ie0110_kluane_load_1m.csv"
)

path_2_wind_resource_data = (
    r"C:\PGMcpp_work\PGMcpp\data\test\resources\ie0110_Wind_2019_1m.csv"
)


# ============================================================
# Model inputs
# ============================================================

model_inputs = PGMcpp.ModelInputs()
model_inputs.path_2_electrical_load_time_series = path_2_electrical_load_time_series

model_inputs.control_mode = PGMcpp.ControlMode.LOAD_FOLLOWING
model_inputs.firm_dispatch_ratio = 0.1
model_inputs.load_reserve_ratio = 0.1

model = PGMcpp.Model(model_inputs)


# ============================================================
# Diesel generators
# ============================================================

diesel_capacities_kW = [600, 400, 310]

for capacity_kW in diesel_capacities_kW:
    diesel_inputs = PGMcpp.DieselInputs()

    diesel_inputs.fuel_cost_L = DIESEL_FUEL_COST_CAD_PER_L
    diesel_inputs.combustion_inputs.production_inputs.capacity_kW = capacity_kW
    diesel_inputs.combustion_inputs.production_inputs.is_sunk = True

    model.addDiesel(diesel_inputs)


# ============================================================
# Wind resource
# ============================================================

wind_resource_key = 1

model.addResource(
    PGMcpp.RenewableType.WIND,
    path_2_wind_resource_data,
    wind_resource_key
)


# ============================================================
# Wind turbine
# ============================================================

wind_capacity_kW = 900

wind_total_capital_cost_CAD = (
    WIND_UNIT_COST_CAD_PER_KW
    * wind_capacity_kW
    * REMOTE_COST_FACTOR
)

wind_inputs = PGMcpp.WindInputs()

wind_inputs.renewable_inputs.production_inputs.capacity_kW = wind_capacity_kW
wind_inputs.renewable_inputs.production_inputs.is_sunk = False
wind_inputs.resource_key = wind_resource_key

# PGMcpp expects total capital cost [CAD], not unit cost [CAD/kW].
# If this is left negative/default, PGMcpp uses its internal C++ cost function.
wind_inputs.capital_cost = wind_total_capital_cost_CAD

model.addWind(wind_inputs)


# ============================================================
# Lithium-ion battery
# ============================================================

liion_power_capacity_kW = 450
liion_energy_capacity_kWh = 670

liion_total_capital_cost_CAD = (
    LIION_UNIT_COST_CAD_PER_KWH
    * liion_energy_capacity_kWh
    * REMOTE_COST_FACTOR
)

liion_inputs = PGMcpp.LiIonInputs()

liion_inputs.storage_inputs.power_capacity_kW = liion_power_capacity_kW
liion_inputs.storage_inputs.energy_capacity_kWh = liion_energy_capacity_kWh

# PGMcpp expects total capital cost [CAD].
# This matches the C++ logic using energy_capacity_kWh.
liion_inputs.capital_cost = liion_total_capital_cost_CAD

model.addLiIon(liion_inputs)


# ============================================================
# Diagnostics
# ============================================================

print("\n--- Script diagnostics ---")
print("Current script:", __file__)

print("\n--- Diesel inputs ---")
print("Diesel capacities [kW]:", diesel_capacities_kW)
print("Diesel fuel cost [CAD/L]:", DIESEL_FUEL_COST_CAD_PER_L)

print("\n--- Wind cost inputs ---")
print("Wind capacity [kW]:", wind_capacity_kW)
print("Wind unit cost [USD/kW]:", WIND_UNIT_COST_USD_PER_KW)
print("Wind unit cost [CAD/kW]:", WIND_UNIT_COST_CAD_PER_KW)
print("Remote cost factor [-]:", REMOTE_COST_FACTOR)
print("Wind total capital cost [CAD]:", wind_total_capital_cost_CAD)

print("\n--- Li-ion cost inputs ---")
print("Li-ion power capacity [kW]:", liion_power_capacity_kW)
print("Li-ion energy capacity [kWh]:", liion_energy_capacity_kWh)
print("Li-ion unit cost [USD/kWh]:", LIION_UNIT_COST_USD_PER_KWH)
print("Li-ion unit cost [CAD/kWh]:", LIION_UNIT_COST_CAD_PER_KWH)
print("Remote cost factor [-]:", REMOTE_COST_FACTOR)
print("Li-ion total capital cost [CAD]:", liion_total_capital_cost_CAD)

print("\n--- Total user-defined CAPEX ---")
print("Total CAPEX [CAD]:", wind_total_capital_cost_CAD + liion_total_capital_cost_CAD)


# ============================================================
# Run model
# ============================================================

model.run()
model.writeResults("FTHIS")