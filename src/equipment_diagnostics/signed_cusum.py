"""Signed standardized one-sided CUSUM with normal-only blocked calibration.

NIST tabular CUSUM supplies the mean-shift statistic, not a guarantee for these
autocorrelated observations. Block-resampled normal paths supply an empirical
finite-horizon limit. This is not an exact reproduction of AR-sieve or stationary
bootstrap papers and does not certify an industrial false-alarm probability.
"""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,finish,number


class SignedResidualCUSUM(Diagnostic):
    kind='signed_residual_cusum'
    reference_metric='positive_signal_magnitude'
    requires_full_history=True
    score_semantics='signed_normal_standardized_cusum_to_calibrated_limit'
    references=('https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm',
                '10.1080/01621459.1994.10476870')

    def __init__(self,channels,*,context_unit='1',reference_step_s=1.,drift_sigma=.25,
                 scale_floor=.05,minimum_limit=5.,prewhiten=False,**kwargs):
        super().__init__(channels,**kwargs)
        if context_unit not in ('1','W'):raise ValueError('context must be identifier1 or measured demandW')
        self.context_unit=context_unit
        self.step=number(reference_step_s,'reference_step_s',positive=True)
        self.drift=number(drift_sigma,'drift_sigma',positive=True)
        self.floor=number(scale_floor,'scale_floor',positive=True)
        self.minimum=number(minimum_limit,'minimum_limit',positive=True)
        if not isinstance(prewhiten,bool):raise ValueError('prewhiten must be boolean')
        self.prewhiten=prewhiten
        self.params=dict(context_unit=context_unit,reference_step_s=self.step,drift_sigma=self.drift,
            scale_floor=self.floor,minimum_limit=self.minimum,prewhiten=prewhiten)

    def _raw(self,batch):
        if self.reference is not None and self.reference.get('signal_basis_id') is not None:
            if batch.metadata.get('signal_basis_id')!=self.reference['signal_basis_id']:
                raise ValueError('derived signal basis differs from normal reference')
        c,v=self._columns(batch,dict(signal='1',context=self.context_unit))
        x,g=c['signal'],c['context'];v &= np.isfinite(x)&np.isfinite(g)
        if self.context_unit=='W':v &= g>0
        z=np.full(len(x),np.nan);limit=np.full(len(x),np.nan)
        if self.reference is None:z[:]=0;limit[:]=self.minimum
        else:
            for group in self.reference['signed_groups']:
                mask=g==group['context']
                z[mask]=(x[mask]-group['center'])/group['scale'];limit[mask]=group.get('limit',self.minimum)
            v &= np.isfinite(z)&np.isfinite(limit)
        reset=np.array([self._break(batch,i,v) or (i>0 and g[i]!=g[i-1]) for i in range(len(x))])
        raw_z=z.copy()
        if self.prewhiten and self.reference is not None:
            for group in self.reference['signed_groups']:
                mask=v&(g==group['context'])&~reset
                previous=np.r_[0.,raw_z[:-1]]
                z[mask]=(raw_z[mask]-group['ar1_phi']*previous[mask]-group['innovation_center'])/group['innovation_scale']
            v &= ~reset
            z[~v]=np.nan
        dt=np.r_[self.step,np.diff(batch.time_s)];dt[reset]=self.step
        return finish(dict(positive_signal_magnitude=np.maximum(abs(x),1e-12),signal=x,context=g,
            raw_standardized_residual=raw_z,standardized_residual=z,limit=limit,reset=reset.astype(float),elapsed_increment_s=dt),v)

    def fit(self,batch,*,minimum_samples=20):
        super().fit(batch,minimum_samples=minimum_samples)
        try:
            basis=batch.metadata.get('signal_basis_id')
            if basis is not None and (not isinstance(basis,str) or not basis.strip()):raise ValueError('nonempty signal basis identifier required')
            self.reference['signal_basis_id']=basis
            c,v=self._columns(batch,dict(signal='1',context=self.context_unit));groups=[]
            if self.context_unit=='W':v &= c['context']>0
            for g in np.unique(c['context'][v]):
                x=c['signal'][v&(c['context']==g)]
                if len(x)<minimum_samples:raise ValueError('insufficient normal context')
                center=float(x.mean());scale=max(self.floor,float(x.std(ddof=1)))
                if not np.isfinite(center) or not np.isfinite(scale):raise ValueError('unrepresentable normal moments')
                group=dict(context=float(g),center=center,scale=scale,accepted_samples=len(x))
                if self.prewhiten:
                    z=(c['signal']-center)/scale
                    pair=np.array([i>0 and v[i] and v[i-1] and c['context'][i]==g and c['context'][i-1]==g
                        and not self._break(batch,i,v) for i in range(len(v))])
                    if pair.sum()<10:raise ValueError('insufficient consecutive normal AR1 pairs')
                    a=np.r_[0.,z[:-1]][pair];b=z[pair]
                    denominator=float(a@a);phi=0. if denominator<1e-12 else float(np.clip((a@b)/denominator,-.99,.99))
                    innovations=b-phi*a;bias=float(innovations.mean());sigma=max(.05,float(innovations.std(ddof=1)))
                    if not np.isfinite(phi+bias+sigma):raise ValueError('invalid innovation moments')
                    group.update(ar1_phi=phi,innovation_center=bias,innovation_scale=sigma,normal_pairs=int(pair.sum()),
                        ar1_assumption='lag1 at observed cadence; no exact irregular-time continuous AR model')
                groups.append(group)
            self.reference['signed_groups']=groups
        except Exception:
            self.reference=None
            raise
        return self

    def _score(self,m):
        total=0.;stat=np.full(len(m['signal']),np.nan)
        for i,z in enumerate(m['standardized_residual']):
            if not np.isfinite(z):total=0.;continue
            if m['reset'][i]:total=0.
            total=max(0.,total+(z-self.drift)*m['elapsed_increment_s'][i]/self.step)
            stat[i]=total
        m['cusum_statistic']=stat
        return stat/m['limit']

    def _alarm_break(self,batch,i,valid,metrics):
        return super()._alarm_break(batch,i,valid,metrics) or bool(metrics['reset'][i])

    def calibrate(self,batch,*,block_s=None,horizon_s=3600.,replicates=256,quantile=.99,seed=20261106):
        """Separate normal calibration; whole observed paths plus block maxima.

        Resamples fixed-sample-length contiguous blocks, WITHOUT crossing real gaps,
        episode/mode boundaries or contexts. Artificial block joins use the
        declared reference cadence. block_s specifies nominal length at that
        cadence; actual observed spans are recorded for irregular sampling.
        No evaluation/fault data are consumed.
        """
        if self.reference is None or batch.fingerprint==self.reference['training_fingerprint']:
            raise ValueError('separate normal calibration required')
        q=number(quantile,'quantile',positive=True);horizon=number(horizon_s,'horizon_s',positive=True)
        if q>=1:raise ValueError('quantile must be <1')
        if isinstance(replicates,bool) or not isinstance(replicates,int) or not 20<=replicates<=10000:
            raise ValueError('replicates must be integer20..10000')
        if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError('nonnegative integer seed required')
        block=None if block_s is None else number(block_s,'block_s',positive=True)
        if block is not None and (block<self.step or horizon<block):raise ValueError('step <= block <= horizon required')
        old=deepcopy(self.reference)
        try:
            for group in self.reference['signed_groups']:group.pop('limit',None)
            m,v,_=self._raw(batch);self._score(m);records=[]
            rng=np.random.default_rng(seed)
            for group in self.reference['signed_groups']:
                valid=v&(m['context']==group['context'])
                if valid.sum()<20:raise ValueError('insufficient calibration context')
                observed=float(np.max(m['cusum_statistic'][valid]));cut=max(self.minimum,observed)
                record=dict(context=group['context'],observed_max=observed,accepted_samples=int(valid.sum()))
                if block is not None:
                    starts=[];lo=0;length=max(2,int(np.ceil(block/self.step)))
                    # Only complete blocks of the declared length are admissible.
                    for i in range(len(v)):
                        if not valid[i]:lo=i+1;continue
                        if m['reset'][i]:lo=i
                        if i-lo+1>=length:starts.append(i-length+1)
                    if not starts:raise ValueError('no continuous calibration block of requested duration')
                    starts=np.asarray(starts);c=np.zeros(replicates);maximum=c.copy();elapsed=c.copy();done=np.zeros(replicates,bool)
                    selected=np.zeros(replicates,int);iterations=0
                    # Normal-only Monte Carlo; keep actual within-block dt.
                    while not done.all():
                        if iterations>=100000:raise ValueError('bootstrap horizon exceeds iteration budget')
                        offset=iterations%length
                        if offset==0:selected=rng.choice(starts,size=replicates)
                        ix=selected+offset
                        dt=np.full(replicates,self.step) if offset==0 else m['elapsed_increment_s'][ix]
                        active=~done&(elapsed+dt<=horizon)
                        done |= elapsed+dt>horizon
                        c[active]=np.maximum(0,c[active]+(m['standardized_residual'][ix[active]]-self.drift)*dt[active]/self.step)
                        maximum=np.maximum(maximum,c);elapsed[active]+=dt[active];iterations+=1
                    boot=float(np.quantile(maximum,q));cut=max(cut,boot)
                    record.update(block_s=block,block_samples=length,admissible_blocks=len(starts),
                        actual_block_span_range_s=[float(np.min(batch.time_s[starts+length-1]-batch.time_s[starts]+self.step)),
                                                   float(np.max(batch.time_s[starts+length-1]-batch.time_s[starts]+self.step))],
                        bootstrap_maxima=maximum.tolist(),bootstrap_quantile=boot,
                        simulated_elapsed_range_s=[float(elapsed.min()),float(elapsed.max())])
                group['limit']=float(np.nextafter(cut,np.inf));record['limit']=group['limit'];records.append(record)
            self.reference['signed_calibration']=dict(fingerprint=batch.fingerprint,block_s=block,horizon_s=horizon,
                replicates=replicates,quantile=q,seed=seed,groups=records,
                caveat='empirical normal blocked calibration, no guaranteed ARL or real-world false-alarm bound')
        except Exception:
            self.reference=old
            raise
        return self

    def set_reference(self,reference):
        basis=reference.get('signal_basis_id')
        if basis is not None and (not isinstance(basis,str) or not basis.strip()):raise ValueError('invalid signal basis identifier')
        groups=reference.get('signed_groups')
        if not isinstance(groups,list) or not groups:raise ValueError('normal signed groups required')
        ids=[]
        for g in groups:
            ids.append(number(g.get('context'),'context'));number(g.get('center'),'center')
            if self.context_unit=='W' and g['context']<=0:raise ValueError('positive nominal demand required')
            number(g.get('scale'),'scale',positive=True)
            if 'limit' in g:number(g['limit'],'limit',positive=True)
            if self.prewhiten:
                phi=number(g.get('ar1_phi'),'ar1_phi')
                if abs(phi)>=1:raise ValueError('stationary AR1 required')
                number(g.get('innovation_center'),'innovation_center');number(g.get('innovation_scale'),'innovation_scale',positive=True)
        if len(ids)!=len(set(ids)):raise ValueError('duplicate context')
        cal=reference.get('signed_calibration')
        if cal is not None:
            if not isinstance(cal,dict) or not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):
                raise ValueError('invalid calibration provenance')
            if any('limit' not in g for g in groups):raise ValueError('incomplete calibration limits')
            records=cal.get('groups')
            if not isinstance(records,list) or sorted(g.get('context') for g in records)!=sorted(ids):
                raise ValueError('incomplete calibration contexts')
            q=number(cal.get('quantile'),'calibration quantile',positive=True)
            if q>=1:raise ValueError('invalid calibration quantile')
            for g in groups:
                record=next(r for r in records if r['context']==g['context'])
                if record.get('limit')!=g['limit']:raise ValueError('inconsistent calibration limit')
        return super().set_reference(reference)
