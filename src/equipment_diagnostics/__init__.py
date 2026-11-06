"""Equipment-specific diagnostics with optional project adapters."""
from .contracts import SensorBatch, DiagnosticResult
from .additional import ColumnHydraulicsDiagnostic, SteamTrapDiagnostic, ChillerPerformanceDiagnostic
from .streaming import StreamingDiagnostic
from .catalog import list_diagnostics
from .heat_pump import HeatPumpPerformanceDiagnostic
from .filter_risk import FilterServiceRiskModel
from .filter_classifier import FilterRiskClassifier
from .temporal_evidence import TemporalEvidenceDiagnostic
from .boosted_filter import FilterBoostedRiskClassifier,FilterBoostedLifeModel
from .residual_coherence import ResidualCoherenceDiagnostic
from .alarm_hysteresis import HysteresisAlarmDiagnostic
from .filter_ensemble import FilterRiskEnsemble
from .diagnostics import (MassBalanceDiagnostic, BoilerBalanceDiagnostic,
                          HeatExchangerDiagnostic, HydraulicResistanceDiagnostic,
                          VaporizerDiagnostic, ROMembraneDiagnostic, ValveTrackingDiagnostic,
                          create_diagnostic, DIAGNOSTICS)

__version__ = "0.17.1"
__all__ = ["SensorBatch", "DiagnosticResult", "MassBalanceDiagnostic", "BoilerBalanceDiagnostic",
           "HeatExchangerDiagnostic", "HydraulicResistanceDiagnostic", "VaporizerDiagnostic",
           "ROMembraneDiagnostic", "ValveTrackingDiagnostic", "create_diagnostic", "DIAGNOSTICS"]
__all__ += ["ColumnHydraulicsDiagnostic", "SteamTrapDiagnostic", "ChillerPerformanceDiagnostic"]
__all__ += ["StreamingDiagnostic", "list_diagnostics"]
__all__ += ['HeatPumpPerformanceDiagnostic']
__all__ += ['FilterServiceRiskModel'] # supervised risk API; separate from normal-reference CLI catalog
__all__ += ['FilterRiskClassifier']
__all__ += ['TemporalEvidenceDiagnostic']
__all__ += ['FilterBoostedRiskClassifier','ResidualCoherenceDiagnostic']
__all__ += ['FilterBoostedLifeModel']
__all__ += ['HysteresisAlarmDiagnostic']
__all__ += ['FilterRiskEnsemble']
from .physical_inputs import (calibrated_level,causal_asof,moist_air_exchange,
    horizontal_cylinder_liquid_volume,SaturatedBoilerInventory,PiecewiseVaporizer)
__all__ += ['calibrated_level','causal_asof','moist_air_exchange',
    'horizontal_cylinder_liquid_volume','SaturatedBoilerInventory','PiecewiseVaporizer']
from .wet_coil import WetCoilAirsideDiagnostic
__all__ += ['WetCoilAirsideDiagnostic']
from .pressure_context import LoadConditionedPressureDiagnostic
__all__ += ['LoadConditionedPressureDiagnostic']
from .signed_cusum import SignedResidualCUSUM
__all__ += ['SignedResidualCUSUM']
from .heat_pump import evaporator_conductance_proxy
__all__ += ['evaporator_conductance_proxy']
from .conditional_residual import ConditionalResidualDiagnostic
__all__ += ['ConditionalResidualDiagnostic']
from .window_change import WindowChangeDiagnostic
__all__ += ['WindowChangeDiagnostic']
