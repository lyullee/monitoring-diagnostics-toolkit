"""Supervised filter-risk boosting, exported to an inspectable NumPy runtime."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,number
from .filter_classifier import FilterRiskClassifier


class FilterBoostedRiskClassifier(FilterRiskClassifier):
    kind='filter_boosted_risk'
    TASK='classification'

    def __init__(self,channels,*,n_estimators=150,min_samples_leaf=30,max_depth=6,random_state=42,
                 learning_rate=.05,max_leaf_nodes=15,l2_regularization=1.,balance_trials=False,**kwargs):
        super().__init__(channels,n_estimators=n_estimators,min_samples_leaf=min_samples_leaf,max_depth=max_depth,random_state=random_state,**kwargs)
        self.rate=number(learning_rate,'learning_rate',positive=True);self.l2=number(l2_regularization,'l2_regularization',nonnegative=True)
        if isinstance(max_leaf_nodes,bool) or not isinstance(max_leaf_nodes,int) or max_leaf_nodes<2:raise ValueError('invalid max_leaf_nodes')
        self.leaves=max_leaf_nodes
        if not isinstance(balance_trials,bool):raise ValueError('invalid balance_trials')
        self.balance_trials=balance_trials
        self.params.update(learning_rate=self.rate,max_leaf_nodes=self.leaves,l2_regularization=self.l2)
        if balance_trials:self.params['balance_trials']=True

    def fit(self,batch,remaining_life_s,*,minimum_samples=20):
        self.reference=None;y=np.asarray(remaining_life_s,float)
        if y.shape!=batch.time_s.shape or not np.isfinite(y).all() or (y<0).any():raise ValueError('invalid remaining life')
        Diagnostic.fit(self,batch,minimum_samples=minimum_samples)
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor
            import sklearn
            from threadpoolctl import threadpool_limits
            metrics,valid,_=self._raw(batch);x=self._features(metrics);valid&=np.isfinite(x).all(axis=1);target=(y[valid]<=self.horizon).astype(int)
            if self.TASK=='classification' and len(np.unique(target))!=2:raise ValueError('both risk classes required')
            # No random internal validation split: all fitting data belong to
            # the declared training trials. The outer calibration stays separate.
            with threadpool_limits(limits=1):
                common=dict(max_iter=self.forest_params['n_estimators'],learning_rate=self.rate,
                    max_depth=self.forest_params['max_depth'],max_leaf_nodes=self.leaves,min_samples_leaf=self.forest_params['min_samples_leaf'],
                    l2_regularization=self.l2,early_stopping=False,random_state=self.forest_params['random_state'])
                weights=None
                if self.balance_trials:
                    _,inverse,count=np.unique(batch.episodes[valid],return_inverse=True,return_counts=True)
                    weights=1./count[inverse];weights*=len(weights)/weights.sum()
                estimator=HistGradientBoostingClassifier(**common,class_weight='balanced') if self.TASK=='classification' else HistGradientBoostingRegressor(**common,loss='squared_error')
                estimator.fit(x[valid],target if self.TASK=='classification' else np.log(np.maximum(y[valid],.1)),sample_weight=weights)
                trees=[]
                for iteration in estimator._predictors:
                    if len(iteration)!=1:raise ValueError('binary boosting required')
                    nodes=iteration[0].nodes;leaf=nodes['is_leaf'].astype(bool)
                    if nodes['is_categorical'].any():raise ValueError('categorical tree export unsupported')
                    trees.append(dict(left=np.where(leaf,-1,nodes['left'].astype(np.int64)).tolist(),right=np.where(leaf,-1,nodes['right'].astype(np.int64)).tolist(),
                        feature=np.where(leaf,-2,nodes['feature_idx']).tolist(),threshold=nodes['num_threshold'].tolist(),vote=nodes['value'].tolist()))
                self.reference['risk_forest']=dict(trees=trees,feature_count=x.shape[1],training_only=True,prediction_mode='additive_logit' if self.TASK=='classification' else 'additive_log_life',
                    fit_library_version=sklearn.__version__)
                self.reference['risk_forest']['baseline_log_odds' if self.TASK=='classification' else 'baseline_log_life']=float(estimator._baseline_prediction[0,0])
                material=metrics.get('dust_class',np.zeros(len(valid)));support=[]
                for value in np.unique(material[valid]):
                    xx=x[valid&(material==value)];support.append(dict(material=float(value),minimum=xx.min(axis=0).tolist(),maximum=xx.max(axis=0).tolist(),samples=len(xx)))
                self.reference['risk_forest']['training_support']=support
                expected=estimator.predict_proba(x[valid])[:,1] if self.TASK=='classification' else self.horizon/np.exp(np.clip(estimator.predict(x[valid]),-20,30))
                if not np.allclose(self._votes(x[valid]),expected,atol=1e-12,rtol=1e-12):raise ValueError('boosting export mismatch')
        except Exception:self.reference=None;raise
        return self

    def _vote_statistics(self,x):
        model=self.reference['risk_forest'];x=np.asarray(x,float);logit=np.full(len(x),model['baseline_log_odds' if self.TASK=='classification' else 'baseline_log_life']);sum_value=np.zeros(len(x));square=np.zeros(len(x))
        for tree in model['trees']:
            left=np.asarray(tree['left'],int);right=np.asarray(tree['right'],int);feature=np.asarray(tree['feature'],int);cut=np.asarray(tree['threshold']);value=np.asarray(tree['vote'])
            node=np.zeros(len(x),int)
            for _ in range(self.forest_params['max_depth']+1):
                active=left[node]!=-1
                if not active.any():break
                ix=np.flatnonzero(active);nn=node[ix];node[ix]=np.where(x[ix,feature[nn]]<=cut[nn],left[nn],right[nn])
            if (left[node]!=-1).any():raise ValueError('tree exceeds depth')
            contribution=value[node];logit+=contribution;sum_value+=contribution;square+=contribution**2
        n=len(model['trees'])
        output=1/(1+np.exp(-np.clip(logit,-700,700))) if self.TASK=='classification' else self.horizon/np.exp(np.clip(logit,-20,30))
        return output,np.sqrt(np.maximum(0.,square/n-(sum_value/n)**2))

    def _score(self,metrics):
        score=super()._score(metrics)
        metrics['boost_contribution_std']=metrics.pop('tree_vote_std')
        return score

    def set_reference(self,reference):
        model=reference.get('risk_forest',{})
        if model.get('prediction_mode')!=('additive_logit' if self.TASK=='classification' else 'additive_log_life'):raise ValueError('invalid boosting reference')
        key='baseline_log_odds' if self.TASK=='classification' else 'baseline_log_life'
        number(model.get(key),key)
        # Reuse the structural/signed reference checks; the original finite
        # leaf contributions are signed log-odds, not vote probabilities.
        proxy=deepcopy(reference)
        for tree in proxy.get('risk_forest',{}).get('trees',[]):
            values=np.asarray(tree.get('vote'),float)
            if not np.isfinite(values).all():raise ValueError('nonfinite contribution')
            tree['vote']=(1/(1+np.exp(-np.clip(values,-700,700)))).tolist()
        super().set_reference(proxy);self.reference=deepcopy(reference)
        return self


class FilterBoostedLifeModel(FilterBoostedRiskClassifier):
    """Log remaining-service-life regression, equalized by training trial."""
    kind='filter_boosted_life'
    TASK='log_life'
    score_semantics='inverse_predicted_service_life_to_calibrated_threshold'

    def __init__(self,channels,**kwargs):
        if kwargs.get('calibration_scope','pooled')!='pooled':raise ValueError('life model requires pooled calibration')
        kwargs.setdefault('balance_trials',True)
        super().__init__(channels,**kwargs)

    def _score(self,metrics):
        score=super()._score(metrics)
        raw=metrics.pop('risk_vote_fraction')
        metrics['predicted_remaining_service_life_s']=self.horizon/raw
        return score
