import os,subprocess,tempfile,unittest
from pathlib import Path
class Checkpoint(unittest.TestCase):
    def test_retries_already_committed_work_after_concurrent_push(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);log=root/'calls';count=root/'push-count';fake=root/'git'
            fake.write_text('''#!/usr/bin/env python3
import os,sys,pathlib
p=pathlib.Path(os.environ['CHECKPOINT_LOG']);p.open('a').write(' '.join(sys.argv[1:])+'\\n')
if sys.argv[1]=='push':
 c=pathlib.Path(os.environ['CHECKPOINT_COUNT']);n=int(c.read_text())+1 if c.exists() else 1;c.write_text(str(n));sys.exit(1 if n==1 else 0)
sys.exit(0)
''');fake.chmod(0o755)
            sleep=root/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o755)
            env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'CHECKPOINT_LOG':str(log),'CHECKPOINT_COUNT':str(count)}
            script=Path(__file__).resolve().parents[1]/'scripts/push-checkpoint.sh'
            subprocess.run(['bash',str(script),'checkpoint','data/test.json'],env=env,check=True)
            calls=log.read_text();self.assertEqual(calls.count('push origin HEAD:main'),2);self.assertNotIn('commit -m',calls)
