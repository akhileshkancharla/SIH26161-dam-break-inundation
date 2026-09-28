"""dam_break: SIH 26161 dam-break inundation modelling framework.

Pipeline: scenario config -> DEM/land-cover ingestion -> breach hydrograph
-> solvers (rapid screening now; Delft3D FM and DualSPHysics adapters) ->
post-processing (rasters, polygons, exports) -> exposure.
"""

from .config import Scenario, load_scenario
from .breach import BreachParams, breach_parameters, hydrograph_from_breach

__version__ = "0.1.0"

__all__ = [
    "Scenario",
    "load_scenario",
    "BreachParams",
    "breach_parameters",
    "hydrograph_from_breach",
    "__version__",
]
