"""Explicit measured-input conversions; no inferred missing sensors or fault labels."""
import numpy as np
from .base import number

def relative_flow(values,reference_in_same_unit):
    """Cancel a common unknown multiplicative unit; not an absolute-flow estimate."""
    reference=number(reference_in_same_unit,'reference_in_same_unit',positive=True)
    with np.errstate(all='ignore'):return np.asarray(values,float)/reference

def filmtec_inverse_temperature_factor(temperature_c):
    """Inverse of FilmTec manual Eq.73/74: empirical 273/298 constants, not 273.15.

    Normalizes measured flow toward 25C. Published formula is used unchanged;
    membrane-specific applicability and osmotic/concentration effects are separate.
    """
    t=np.asarray(temperature_c,float)
    with np.errstate(all='ignore'):
        factor=np.exp(np.where(t>=25,2640.,3020.)*(1/(273.+t)-1/298.))
    return np.where((t>-273)&np.isfinite(t),factor,np.nan)

def ideal_nacl_osmotic_pressure(concentration_kg_m3,temperature_k):
    """Ideal fully dissociated NaCl van't Hoff approximation in Pa.

    No activity/concentration-polarization correction. This is an explicitly
    approximate input model, not a certified seawater property calculation.
    """
    c,t=np.broadcast_arrays(np.asarray(concentration_kg_m3,float),np.asarray(temperature_k,float))
    with np.errstate(all='ignore'):p=2.*c/.05844*8.31446261815324*t
    return np.where((c>=0)&(t>0)&np.isfinite(c)&np.isfinite(t),p,np.nan)
