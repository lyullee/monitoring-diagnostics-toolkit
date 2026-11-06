"""Qualified input models. SI parameters are explicit; missing plant data are never inferred."""
from copy import deepcopy
import numpy as np
from .base import number
from .contracts import SensorBatch


def append_observations(batch, columns, *, metadata=None):
    """Append {name: (values, unit, quality)} without losing identity or segmentation."""
    if set(columns) & set(batch.channels):
        raise ValueError('derived channel must not overwrite an observation')
    n=len(batch.time_s); values=[]; valid=[]; units=[]
    for name,(x,unit,good) in columns.items():
        a=np.asarray(x,float); q=np.asarray(good,bool)
        if a.shape!=(n,) or q.shape!=(n,): raise ValueError('derived arrays must match batch length')
        values.append(a); valid.append(q); units.append(unit)
    meta=deepcopy(batch.metadata)
    if metadata: meta.update(deepcopy(metadata))
    return SensorBatch(batch.time_s,np.column_stack((batch.values,*values)),
        (*batch.channels,*columns),(*batch.units,*units),batch.clock_id,batch.asset_id,batch.origin,
        np.column_stack((batch.valid,*valid)),batch.episodes,batch.modes,meta)


def calibrated_level(batch, channel, *, slope_m_v, offset_m, qualified_voltage_range_v,
                     output='level_m'):
    """Linear pressure-transducer calibration; extrapolation is invalid, never clipped."""
    slope=number(slope_m_v,'slope_m_v',positive=True)
    offset=number(offset_m,'offset_m')
    low,high=qualified_voltage_range_v
    low=number(low,'voltage lower bound'); high=number(high,'voltage upper bound')
    if low>=high: raise ValueError('ordered qualified voltage range required')
    x,good=batch.column(channel,'V')
    with np.errstate(all='ignore'): level=slope*x+offset
    good=good&(x>=low)&(x<=high)&np.isfinite(level)&(level>=0)
    return append_observations(batch,{output:(level,'m',good)},metadata={
        'level_calibration':dict(source_channel=channel,slope_m_v=slope,offset_m=offset,
                                 qualified_voltage_range_v=[low,high])})


def causal_asof(source, target, *, max_age_s):
    """Last observation available on the same declared clock, episode and mode.

    Source timestamps must denote availability, not an uncorrected sensor clock.
    No forward interpolation, carry across gaps, clock conversion or unit inference.
    """
    age=number(max_age_s,'max_age_s',nonnegative=True)
    if (source.clock_id,source.asset_id,source.origin)!=(target.clock_id,target.asset_id,target.origin):
        raise ValueError('alignment requires the same explicit clock, asset and origin')
    if (source.modes is None)!=(target.modes is None): raise ValueError('mode metadata mismatch')
    if set(source.channels)&set(target.channels): raise ValueError('duplicate aligned channels')
    ix=np.searchsorted(source.time_s,target.time_s,side='right')-1
    j=np.maximum(ix,0)
    good=(ix>=0)&(target.time_s-source.time_s[j]<=age)&(source.episodes[j]==target.episodes)
    if source.modes is not None: good &= source.modes[j]==target.modes
    return append_observations(target,{name:(source.values[j,k],unit,source.valid[j,k]&good)
        for k,(name,unit) in enumerate(zip(source.channels,source.units))},
        metadata={'asof_source_fingerprint':source.fingerprint,'max_age_s':age})


def moist_air_exchange(dry_air_flow_kg_s, inlet_temperature_k, outlet_temperature_k,
                       inlet_humidity_kg_kg, outlet_humidity_kg_kg):
    """ASHRAE-style ideal moist-air enthalpy balance, per kg dry air.

    h=1006*T_C + w*(2501000+1860*T_C) J/kg_da. The moisture removal
    rate is not a validated frost-growth rate: liquid drainage and frost enthalpy
    are not measured here. No dry two-sided UA or brine flow is manufactured.
    """
    arrays=np.broadcast_arrays(*[np.asarray(x,float) for x in
        (dry_air_flow_kg_s,inlet_temperature_k,outlet_temperature_k,
         inlet_humidity_kg_kg,outlet_humidity_kg_kg)])
    m,ti,to,wi,wo=arrays
    valid=np.logical_and.reduce([np.isfinite(x) for x in arrays])
    valid &= (m>0)&(ti>=173.15)&(ti<=373.15)&(to>=173.15)&(to<=373.15)&(wi>=0)&(wo>=0)&(wi<=.1)&(wo<=.1)
    with np.errstate(all='ignore'):
        hi=1006*(ti-273.15)+wi*(2501000+1860*(ti-273.15))
        ho=1006*(to-273.15)+wo*(2501000+1860*(to-273.15))
        q=m*(hi-ho); removal=m*(wi-wo)
    valid &= np.isfinite(q)&np.isfinite(removal)
    return dict(air_side_heat_w=np.where(valid,q,np.nan),
        moisture_removal_kg_s=np.where(valid,removal,np.nan),valid=valid)


def horizontal_cylinder_liquid_volume(level_m, *, radius_m, length_m):
    """Circular segment volume; flat heads only. Invalid levels return NaN."""
    r=number(radius_m,'radius_m',positive=True); length=number(length_m,'length_m',positive=True)
    h=np.asarray(level_m,float); good=np.isfinite(h)&(h>=0)&(h<=2*r)
    # Use the smaller segment, and a small-angle series to avoid cancellation.
    low=np.minimum(h,2*r-h)
    with np.errstate(all='ignore'):
        theta=2*np.arcsin(np.sqrt(np.clip(low/(2*r),0,1)))
        segment=np.where(theta<.01,
            theta**3*(2/3-theta**2*(2/15-theta**2*4/315)),theta-np.sin(theta)*np.cos(theta))
        small=length*r*r*segment; full=np.pi*r*r*length
        volume=np.where(h<=r,small,full-small)
    if not np.isfinite(full) or full<=0: raise ValueError('unrepresentable drum volume')
    # A positive segment lost to underflow must not become an empty drum.
    good &= ~((h>0)&(volume==0))
    return np.where(good,volume,np.nan)


class SaturatedBoilerInventory:
    """Configured equilibrium inventory, NOT an unobserved swell/void estimator.

    Pressure must be absolute Pa. Level is geometric height from drum bottom,
    not raw DP or indicated percent. Every connected circuit volume and its
    measured/externally estimated vapor void fraction must be supplied.
    """
    def __init__(self, *, radius_m, length_m, circuit_volumes_m3):
        self.radius=number(radius_m,'radius_m',positive=True)
        self.length=number(length_m,'length_m',positive=True)
        if not isinstance(circuit_volumes_m3,dict) or not circuit_volumes_m3:
            raise ValueError('explicit connected circuit volumes required')
        self.circuits={k:number(v,'circuit volume',positive=True) for k,v in circuit_volumes_m3.items()}
        if any(not isinstance(k,str) or not k for k in self.circuits): raise ValueError('circuit names required')
        self.volume=float(horizontal_cylinder_liquid_volume(2*self.radius,radius_m=self.radius,length_m=self.length))
        if not np.isfinite(self.volume+sum(self.circuits.values())): raise ValueError('unrepresentable total volume')

    def transform(self,batch,*,pressure_channel,level_channel,void_channels,output='inventory_kg'):
        if set(void_channels)!=set(self.circuits): raise ValueError('all circuit void fractions required')
        role_channels=[pressure_channel,level_channel,*void_channels.values()]
        if len(set(role_channels))!=len(role_channels): raise ValueError('inventory roles must use distinct channels')
        p,good=batch.column(pressure_channel,'Pa'); h,q=batch.column(level_channel,'m'); good=good&q
        volume=horizontal_cylinder_liquid_volume(h,radius_m=self.radius,length_m=self.length)
        liquid=volume.copy(); vapor=self.volume-volume
        for name,total in self.circuits.items():
            a,q=batch.column(void_channels[name],'1'); good &= q&(a>=0)&(a<=1)
            liquid+=total*(1-a); vapor+=total*a
        good &= (p>611.657)&(p<22.064e6)&np.isfinite(volume)
        from CoolProp.CoolProp import PropsSI
        rl=np.full(len(p),np.nan); rv=rl.copy()
        for i in np.flatnonzero(good):
            try:
                rl[i]=PropsSI('D','P',float(p[i]),'Q',0,'Water')
                rv[i]=PropsSI('D','P',float(p[i]),'Q',1,'Water')
            except ValueError: good[i]=False
        with np.errstate(all='ignore'): inventory=rl*liquid+rv*vapor
        good &= np.isfinite(inventory)&(inventory>0)
        return append_observations(batch,{output:(inventory,'kg',good)},metadata={
            'inventory_model':dict(kind='configured_saturated_equilibrium',radius_m=self.radius,
                length_m=self.length,circuit_volumes_m3=self.circuits,void_channels=void_channels,
                property_basis='CoolProp::Water',excludes='unmeasured swell, slip and subcooled sections')})


class PiecewiseVaporizer:
    """Steady isobaric preheat/boil/superheat against a constant-temperature source.

    Qualified constant cp, latent heat and saturation temperature are supplied
    by the caller for ONE fluid/pressure. Enthalpy is relative to saturated liquid.
    UA includes all thermal resistances. No pressure drop, icing dynamics,
    multicomponent glide or source cooling is inferred.
    """
    def __init__(self, *, saturation_temperature_k, latent_heat_j_kg,
                 liquid_cp_j_kg_k, vapor_cp_j_kg_k, ua_w_k, property_basis_id):
        self.ts=number(saturation_temperature_k,'saturation_temperature_k',positive=True)
        self.latent=number(latent_heat_j_kg,'latent_heat_j_kg',positive=True)
        self.cl=number(liquid_cp_j_kg_k,'liquid_cp_j_kg_k',positive=True)
        self.cv=number(vapor_cp_j_kg_k,'vapor_cp_j_kg_k',positive=True)
        self.ua=number(ua_w_k,'ua_w_k',positive=True)
        if not isinstance(property_basis_id,str) or not property_basis_id.strip(): raise ValueError('property_basis_id required')
        self.basis=property_basis_id

    def predict(self,mass_flow_kg_s,inlet_relative_enthalpy_j_kg,source_temperature_k):
        m,hin,source=np.broadcast_arrays(*[np.asarray(a,float) for a in
            (mass_flow_kg_s,inlet_relative_enthalpy_j_kg,source_temperature_k)])
        with np.errstate(all='ignore'):
            tin=self.ts+np.where(hin<0,hin/self.cl,np.where(hin>self.latent,(hin-self.latent)/self.cv,0))
            valid=np.isfinite(m)&np.isfinite(hin)&np.isfinite(source)&(m>0)&(tin>0)&(source>self.ts)&(source>=tin)
            ua=np.full(m.shape,self.ua); h=hin.copy()
            pre=hin<0
            need=m*self.cl*np.log1p((self.ts-tin)/(source-self.ts))
            used=np.where(pre,np.minimum(ua,need),0)
            h=np.where(pre,hin+(source-tin)*self.cl*(-np.expm1(-used/(m*self.cl))),h)
            h=np.where(pre&(ua>=need),0,h); ua-=used
            boil=(h>=0)&(h<self.latent)
            rise=np.minimum(self.latent-h,ua*(source-self.ts)/m)
            h=np.where(boil,h+rise,h)
            ua-=np.where(boil,m*rise/(source-self.ts),0)
            superheated=h>=self.latent
            t0=self.ts+(h-self.latent)/self.cv
            h=np.where(superheated,h+self.cv*(source-t0)*(-np.expm1(-np.maximum(ua,0)/(m*self.cv))),h)
            tout=self.ts+np.where(h<0,h/self.cl,np.where(h>self.latent,(h-self.latent)/self.cv,0))
            duty=m*(h-hin); fraction=np.clip(h/self.latent,0,1)
        valid &= np.isfinite(tout)&np.isfinite(h)&np.isfinite(duty)&((duty>0)|(source==tin))&(tout<=source)
        return {**{k:np.where(valid,v,np.nan) for k,v in dict(outlet_temperature_k=tout,
            outlet_relative_enthalpy_j_kg=h,absorbed_duty_w=duty,vapor_fraction=fraction).items()},'valid':valid}

    def transform(self,batch,*,mass_flow_channel,inlet_enthalpy_channel,source_temperature_channel,
                  output='predicted_outlet_k'):
        if batch.metadata.get('enthalpy_basis_id')!=self.basis: raise ValueError('explicit matching enthalpy basis required')
        m,gm=batch.column(mass_flow_channel,'kg/s'); h,gh=batch.column(inlet_enthalpy_channel,'J/kg')
        s,gs=batch.column(source_temperature_channel,'K'); r=self.predict(m,h,s)
        return append_observations(batch,{output:(r['outlet_temperature_k'],'K',gm&gh&gs&r['valid'])},
            metadata={'vaporizer_prediction':dict(property_basis_id=self.basis,ua_w_k=self.ua,
                saturation_temperature_k=self.ts,latent_heat_j_kg=self.latent,
                liquid_cp_j_kg_k=self.cl,vapor_cp_j_kg_k=self.cv,model='steady_piecewise_constant_properties')})
