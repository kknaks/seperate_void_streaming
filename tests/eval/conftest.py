"""eval test conftest — huggingface_hub use_auth_token 호환성 패치.

integration/conftest.py 와 동일한 패치 적용 (huggingface_hub >= 1.0 호환).
"""

from __future__ import annotations

import functools

import huggingface_hub as _hf_hub

_orig_hf_hub_download = _hf_hub.hf_hub_download


@functools.wraps(_orig_hf_hub_download)
def _patched_hf_hub_download(*args, **kwargs):
    if "use_auth_token" in kwargs:
        token = kwargs.pop("use_auth_token")
        kwargs.setdefault("token", token)
    return _orig_hf_hub_download(*args, **kwargs)


_hf_hub.hf_hub_download = _patched_hf_hub_download

try:
    import pyannote.audio.core.model as _pa_model
    _pa_model.hf_hub_download = _patched_hf_hub_download
except Exception:
    pass

try:
    import pyannote.audio.utils.reproducibility as _pa_repro
    _pa_repro.hf_hub_download = _patched_hf_hub_download
except Exception:
    pass
