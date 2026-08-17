"""
Builds a features_esc_<tag>.parquet variant with LOOKBACK_H overridden, using
the SAME build() function 02_build_features.py uses for the deployed model --
not a reimplementation, so it can't silently diverge from the real pipeline.

Run as its own process per variant (EWS_TAG must already be set in the
environment before this starts, since config.py reads it once at import):
  EWS_TAG=esc_lb8  PYTHONUTF8=1 py -3 run_lookback_variant.py 8
  EWS_TAG=esc_lb12 PYTHONUTF8=1 py -3 run_lookback_variant.py 12
"""
import sys
import config

override_h = int(sys.argv[1])
config.LOOKBACK_H = override_h
print(f"TAG={config.TAG}  LOOKBACK_H overridden to {config.LOOKBACK_H}")

import importlib.util
spec = importlib.util.spec_from_file_location("build_features_02", "02_build_features.py")
mod = importlib.util.module_from_spec(spec)
mod.config = config  # same already-patched config object, not a fresh import
spec.loader.exec_module(mod)
mod.build()
