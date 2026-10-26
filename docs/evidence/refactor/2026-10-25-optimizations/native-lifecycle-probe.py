"""Run the real NTFS lifecycle regression against pre-fix and corrected workers."""
import importlib.util,json,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
import pytest
from am3d.ai import test_worker as tests
current=tests.worker
spec=importlib.util.spec_from_file_location('am3d.ai._pre_fix_worker',root/'work/refactor-optimizations/frozen-source/am3d/ai/worker.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
out=root/'work/refactor-optimizations/native-lifecycle-comparison';out.mkdir(exist_ok=False)
results=[]
for label,module in [('pre_fix',baseline),('corrected',current)]:
    for kind in ['file','directory']:
        for publication in ['removed','replaced']:
            case=out/f'{label}-{kind}-{publication}';case.mkdir()
            with pytest.MonkeyPatch.context() as patch:
                tests.worker=module
                try:
                    tests.test_native_deleted_handle_path_is_tolerated_live_but_not_final(case,patch,kind,publication)
                    verdict='live_passes_and_final_rejects'
                    assert label=='corrected'
                except current.PolicyError as exc:
                    assert label=='pre_fix' and getattr(exc,'reason',None)=='containment'
                    verdict='live_rejected_containment'
                finally:
                    tests.worker=current
            results.append({'version':label,'entry_kind':kind,'publication':publication,'result':verdict})
(out/'comparison.json').write_text(json.dumps({'qualification':'Controlled real Windows NTFS handles, no private paths retained; same regression called for both versions. Historical unclassified failure cannot be retrospectively attributed with certainty.','cases':results},indent=2)+'\n')
print(json.dumps(results,indent=2))
