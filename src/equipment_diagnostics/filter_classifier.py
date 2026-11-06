"""Supervised causal risk classification with an inspectable NumPy tree runtime."""
import numpy as np
from .base import Diagnostic,number
from .filter_risk import FilterServiceRiskModel


class FilterRiskClassifier(FilterServiceRiskModel):
    kind='filter_risk_classifier'
    score_semantics='tree_vote_to_calibrated_threshold'
    requires_full_history=True # elapsed trial age must survive stream chunk boundaries

    def __init__(self,channels,*,n_estimators=128,min_samples_leaf=30,max_depth=12,random_state=42,calibration_scope='pooled',feature_set='basic',**kwargs):
        super().__init__(channels,**kwargs)
        self.use_dust='dust_feed_ratio' in channels
        if self.use_dust!=('dust_class' in channels):raise ValueError('both dust conditions required together')
        if calibration_scope not in ('pooled','material') or (calibration_scope=='material' and not self.use_dust):raise ValueError('invalid calibration_scope')
        self.calibration_scope=calibration_scope
        if calibration_scope!='pooled':self.params['calibration_scope']=calibration_scope
        if feature_set not in ('basic','dose') or (feature_set=='dose' and not self.use_dust):raise ValueError('invalid feature_set')
        self.feature_set=feature_set
        if feature_set!='basic':self.params['feature_set']=feature_set
        for name,value in [('n_estimators',n_estimators),('min_samples_leaf',min_samples_leaf),('max_depth',max_depth),('random_state',random_state)]:
            if isinstance(value,bool) or not isinstance(value,int) or value<(0 if name=='random_state' else 1):raise ValueError('invalid '+name)
        self.forest_params=dict(n_estimators=n_estimators,min_samples_leaf=min_samples_leaf,max_depth=max_depth,random_state=random_state)
        self.params.update(self.forest_params)

    def _raw(self,batch):
        m,v,reasons=super()._raw(batch)
        c,good=self._columns(batch,dict(pressure_drop='Pa',flow_ratio='1'),dict(dust_feed_ratio='1',dust_class='1'))
        good&=(c['pressure_drop']>=0)&(c['flow_ratio']>0)
        if self.use_dust:
            condition_ok=(c['dust_feed_ratio']>0)&np.isin(c['dust_class'],[1,2,3])
            good&=condition_ok;v&=good
            reasons[~condition_ok]='invalid_observed_dust_conditions'
        elapsed=np.zeros(len(v));short=np.zeros(len(v));noise=np.zeros(len(v));start=0;left=0
        for i in range(len(v)):
            if self._break(batch,i,good):start=i;left=i
            elapsed[i]=batch.time_s[i]-batch.time_s[start]
            while left<i and batch.time_s[left]<batch.time_s[i]-2.:left+=1
            if good[i] and i-left>=2:
                t=batch.time_s[left:i+1];z=np.log1p(c['pressure_drop'][left:i+1]);dt=t-t.mean()
                short[i]=np.dot(dt,z-z.mean())/np.dot(dt,dt);noise[i]=np.std(z)
        m.update(elapsed_s=elapsed,short_log_growth_per_s=short,short_log_pressure_std=noise)
        if self.feature_set=='dose':
            with np.errstate(all='ignore'):
                m['log_dose_proxy']=np.logaddexp(0.,np.log(elapsed)+np.log(c['dust_feed_ratio']))
                m['log_reference_flow_pressure']=np.logaddexp(0.,np.log(c['pressure_drop'])-2*np.log(c['flow_ratio']))
                m['growth_per_feed_ratio']=m['log_growth_per_s']/c['dust_feed_ratio']
        return m,v,reasons

    def _features(self,m):
        base=FilterServiceRiskModel._features(m)
        x=np.column_stack((base,np.log1p(m['elapsed_s']),m['short_log_growth_per_s'],m['short_log_pressure_std']))
        if 'dust_feed_ratio' in m:x=np.column_stack((x,np.log(m['dust_feed_ratio']),m['dust_class']))
        if self.feature_set=='dose':x=np.column_stack((x,m['log_dose_proxy'],m['log_reference_flow_pressure'],m['growth_per_feed_ratio']))
        return x

    def fit(self,batch,remaining_life_s,*,minimum_samples=20):
        self.reference=None;y=np.asarray(remaining_life_s,float)
        if y.shape!=batch.time_s.shape or not np.isfinite(y).all() or (y<0).any():raise ValueError('invalid remaining life')
        Diagnostic.fit(self,batch,minimum_samples=minimum_samples)
        try:
            from sklearn.ensemble import ExtraTreesClassifier
            m,v,_=self._raw(batch);x=self._features(m);v&=np.isfinite(x).all(axis=1)
            target=(y[v]<=self.horizon).astype(int)
            if len(np.unique(target))!=2:raise ValueError('both service-risk classes required')
            estimator=ExtraTreesClassifier(**self.forest_params,class_weight='balanced',n_jobs=1).fit(x[v],target)
            trees=[]
            for e in estimator.estimators_:
                t=e.tree_;values=t.value[:,0,:];votes=values[:,1]/values.sum(axis=1)
                trees.append(dict(left=t.children_left.tolist(),right=t.children_right.tolist(),feature=t.feature.tolist(),threshold=t.threshold.tolist(),vote=votes.tolist()))
            self.reference['risk_forest']=dict(trees=trees,feature_count=x.shape[1],training_only=True)
            support=[]
            material=m.get('dust_class',np.zeros(len(v)))
            for value in np.unique(material[v]):
                rows=x[v&(material==value)]
                support.append(dict(material=float(value),minimum=rows.min(axis=0).tolist(),maximum=rows.max(axis=0).tolist(),samples=len(rows)))
            self.reference['risk_forest']['training_support']=support
            # Independently verify the exported runtime against sklearn, on fit
            # samples only. There is no sklearn dependency during inference.
            predicted=self._votes(x[v])
            if not np.allclose(predicted,estimator.predict_proba(x[v])[:,1],atol=1e-12):raise ValueError('forest export mismatch')
        except Exception:self.reference=None;raise
        return self

    def set_reference(self,reference):
        model=reference.get('risk_forest',{})
        size=13 if self.feature_set=='dose' else 10 if self.use_dust else 8
        if model.get('feature_count')!=size or len(model.get('trees',[]))!=self.forest_params['n_estimators']:raise ValueError('invalid forest schema')
        for t in model['trees']:
            if set(t)!={'left','right','feature','threshold','vote'}:raise ValueError('invalid tree fields')
            arrays={k:np.asarray(v) for k,v in t.items()};n=len(arrays['left'])
            if not n or any(a.shape!=(n,) or not np.isfinite(a).all() for a in arrays.values()):raise ValueError('invalid tree arrays')
            leaf=arrays['left']==-1
            if ((arrays['right']==-1)!=leaf).any():raise ValueError('invalid leaf')
            for k in ('left','right','feature'):
                if not np.equal(arrays[k],np.floor(arrays[k])).all():raise ValueError('noninteger tree index')
            for k in ('left','right'):
                if ((arrays[k][~leaf]<=np.arange(n)[~leaf])|(arrays[k][~leaf]>=n)).any():raise ValueError('cyclic or invalid tree')
            if ((arrays['feature'][~leaf]<0)|(arrays['feature'][~leaf]>=size)).any():raise ValueError('invalid feature')
            if ((arrays['vote']<0)|(arrays['vote']>1)).any():raise ValueError('invalid vote')
        cal=reference.get('risk_calibration')
        if cal:
            number(cal.get('threshold'),'threshold',positive=True)
            if not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):raise ValueError('separate calibration required')
            if self.calibration_scope=='material':
                groups=cal.get('material_thresholds')
                if not isinstance(groups,list) or sorted(g.get('material') for g in groups)!=[1.,2.,3.]:raise ValueError('missing material thresholds')
                for g in groups:number(g.get('threshold'),'material threshold',positive=True)
        support=model.get('training_support')
        if support is not None:
            if not isinstance(support,list) or not support:raise ValueError('invalid support')
            materials=[]
            for g in support:
                value=number(g.get('material'),'support material',nonnegative=True);materials.append(value)
                if value not in ([1.,2.,3.] if self.use_dust else [0.]):raise ValueError('invalid support material')
                lo=np.asarray(g.get('minimum'),float);hi=np.asarray(g.get('maximum'),float)
                if lo.shape!=(size,) or hi.shape!=(size,) or not np.isfinite(lo).all() or not np.isfinite(hi).all() or (lo>hi).any():raise ValueError('invalid support bounds')
            if len(set(materials))!=len(materials):raise ValueError('duplicate support material')
        return Diagnostic.set_reference(self,reference)

    def _vote_statistics(self,x):
        votes=np.zeros(len(x));squares=np.zeros(len(x))
        # sklearn tree splits operate on float32 inputs. Preserve that declared
        # quantization in this exported runtime, including threshold ties.
        x=np.asarray(x,dtype=np.float32)
        for tree in self.reference['risk_forest']['trees']:
            left=np.asarray(tree['left'],int);right=np.asarray(tree['right'],int)
            feature=np.asarray(tree['feature'],int);cut=np.asarray(tree['threshold']);value=np.asarray(tree['vote'])
            nodes=np.zeros(len(x),int)
            for _ in range(self.forest_params['max_depth']+1):
                active=left[nodes]!=-1
                if not active.any():break
                ix=np.flatnonzero(active);nn=nodes[ix]
                nodes[ix]=np.where(x[ix,feature[nn]]<=cut[nn],left[nn],right[nn])
            if (left[nodes]!=-1).any():raise ValueError('tree exceeds declared depth')
            votes+=value[nodes]
            squares+=value[nodes]**2
        n=len(self.reference['risk_forest']['trees']);mean=votes/n
        return mean,np.sqrt(np.maximum(0.,squares/n-mean**2))

    def _votes(self,x):return self._vote_statistics(x)[0]

    def calibrate(self,batch,remaining_life_s,*,negative_quantile=.95):
        if self.calibration_scope=='pooled':return super().calibrate(batch,remaining_life_s,negative_quantile=negative_quantile)
        from copy import deepcopy
        previous=deepcopy(self.reference)
        try:
            super().calibrate(batch,remaining_life_s,negative_quantile=negative_quantile)
            r=self.score(batch);y=np.asarray(remaining_life_s,float);groups=[]
            for material in (1.,2.,3.):
                mask=r.valid&(r.metrics['dust_class']==material)&(y>self.horizon)
                if mask.sum()<20:raise ValueError('insufficient negative material calibration')
                cut=max(1e-12,float(np.nextafter(np.quantile(r.metrics['risk_vote_fraction'][mask],negative_quantile),np.inf)))
                groups.append(dict(material=material,threshold=cut,negative_samples=int(mask.sum())))
            self.reference['risk_calibration']['material_thresholds']=groups
        except Exception:self.reference=previous;raise
        return self

    def _score(self,metrics):
        x=self._features(metrics);votes,std=self._vote_statistics(x);metrics['risk_vote_fraction']=votes;metrics['tree_vote_std']=std
        support=self.reference['risk_forest'].get('training_support',[])
        fraction=np.zeros(len(x));available=np.zeros(len(x));material=metrics.get('dust_class',np.zeros(len(x)))
        for group in support:
            mask=material==group['material'];available[mask]=1
            fraction[mask]=np.mean((x[mask]>=np.asarray(group['minimum']))&(x[mask]<=np.asarray(group['maximum'])),axis=1)
        metrics['training_support_available']=available;metrics['training_support_fraction']=fraction
        cut=np.full(len(votes),self.reference.get('risk_calibration',{}).get('threshold',1.))
        for group in self.reference.get('risk_calibration',{}).get('material_thresholds',[]):cut[material==group['material']]=group['threshold']
        return votes/cut
