"""Hand-computed legacy C# examples, distinct from Java and iterative clipping."""
import math

import numpy as np
import pytest

from rawtims.rules import (
    RuleProposal,
    legacy_chauvenet_rejections,
    legacy_two_sigma_rejections,
    propose,
)


def test_two_sigma_one_pass_and_existing_selection():
    # n=7, mean=16/7, sample SD=sqrt(81/7); extreme z=6/sqrt(7)>2.
    values = np.array([1.] * 6 + [10.])
    assert (10-values.mean()) / values.std(ddof=1) == pytest.approx(6/math.sqrt(7))
    assert legacy_two_sigma_rejections(values).tolist() == [6]
    assert legacy_two_sigma_rejections(values, [True]*6+[False]).tolist() == []
    assert legacy_two_sigma_rejections([1,1,1,1,6]).tolist() == []
    assert legacy_two_sigma_rejections([1,1,100]).tolist() == []


def test_chauvenet_repeats_single_extreme_and_live_guard():
    # n=12: z(10)=3.1016, criterion~0.0231. Recompute n=11:
    # z(3)=10/sqrt(11), criterion~0.0283. The ten equal values have SD=0.
    v = [1.]*10 + [3., 10.]
    assert legacy_chauvenet_rejections(v).tolist() == [10,11]
    assert legacy_chauvenet_rejections([1,1,100]).tolist() == []
    assert legacy_chauvenet_rejections(v, probability=0).tolist() == []
    assert legacy_chauvenet_rejections([0, -100, float('nan'), 1,1,100]).tolist() == []
    with pytest.raises(ValueError):
        legacy_chauvenet_rejections(v, probability=2)


@pytest.mark.parametrize('rule', ['legacy_two_sigma','legacy_chauvenet'])
def test_legacy_proposal_roundtrip_scope_and_shared(rule):
    v = np.array([[1.,1.]]*10 + [[3.,1.],[10.,1.]])
    p = propose(rule, v, np.ones_like(v,dtype=bool), ['a','b'], [True,True], np.ones(12))
    assert p.rejected['a'] and not p.rejected['b']
    assert p.synced and 'Legacy' in p.describe()
    assert RuleProposal.from_dict(p.to_dict()) == p
