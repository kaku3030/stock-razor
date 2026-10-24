import importlib.util
from dataclasses import asdict

import numpy as np
import pytest

from src.services.strategy_lab.s3_mtf import Rules

spec = importlib.util.spec_from_file_location("s3_validation", "scripts/run_s3_mtf_validation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_holm_is_monotone_and_family_corrected():
    assert module.holm({"a":.01,"b":.04,"c":.03}) == {"a":.03,"c":.06,"b":.06}


def test_centered_null_direction_and_zero_edge():
    for value in (0., .001, -.001):
        x = module.block_test(np.full(240,value),20,999)
        assert x["one_sided_null_bootstrap_p"] == (.001 if value>0 else 1.)


@pytest.mark.parametrize("key", ["manifest_sha256", "source_sha256", "rules", "TRADE_EXECUTION", "promotion"])
def test_wrong_primary_cannot_gain_current_experiment_lineage(key):
    rules = asdict(Rules())
    status = dict(manifest_sha256="m",source_sha256="s",rules=rules,TRADE_EXECUTION="NO",promotion="NO")
    module.verify_primary(status,"m","s",rules)
    status[key] = "WRONG"
    with pytest.raises(ValueError,match="PROVENANCE"):
        module.verify_primary(status,"m","s",rules)
