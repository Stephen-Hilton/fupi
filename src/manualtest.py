import os, sys

bkup_sys_path = sys.path.copy()

def reset(header):
    print(header)
    sys.path = bkup_sys_path.copy() # restore 
    # like all imports, fupi only auto-runs when loaded the first time
    if 'fupi' in sys.modules: del sys.modules['fupi'] # force re-import



reset('-------- NO fupi -------')
[print(p) for p in sys.path]



reset('-------- fupi auto-run: -------')
import fupi
[print(p) for p in sys.path]



reset('-------- fupi auto-run, with envars: -------')
os.environ['FUPI_ADD_DIR_NAMES'] = 'dist'     # envars are additive to defaults
os.environ['FUPI_SKIP_DIR_PATTERNS'] = 'some' # envars are additive to defaults
import fupi
[print(p) for p in sys.path]




reset('-------- fupi manual (not auto-run): -------')
from fupi import ManualFupi 
mf = ManualFupi()
mf.add_dir_names=['src','test','dist'] # these override defaults
[print(p) for p in sys.path] 
# this should be the same as "NO fupi", since it wasn't .run()



reset('-------- fupi manual (manual-run): -------')
from fupi import ManualFupi 
mf = ManualFupi(add_dir_names=['test']) # these override defaults
mf.run()
[print(p) for p in sys.path] # run() should have added only 'test' paths



reset('-------- fupi will not remove from original sys.path: -------')
from fupi import ManualFupi 
mf = ManualFupi(skip_dir_patterns=['Python*','venv*','*egg*']) # these override defaults
mf.run()
[print(p) for p in sys.path] # still has Python* paths from original sys.path


 
 
