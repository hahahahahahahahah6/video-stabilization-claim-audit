import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from video_stabilization_claim_audit import phrases
from video_stabilization_claim_audit.audit import audit, main, source_evidence

EXPECTED_POS = ('video stabilization',
 'video stabilisation',
 'stabilize video',
 'stabilizes video',
 'stabilizing video',
 'stabilise video',
 'stabilises video',
 'stabilising video',
 'stabilized video',
 'stabilised video',
 'stabilize videos',
 'stabilizes videos',
 'video stabilizer',
 'video stabiliser',
 'stabilize footage',
 'stabilizes footage',
 'stabilize shaky video',
 'stabilizes shaky video',
 'shaky video stabilization',
 'camera shake removal',
 'remove camera shake',
 'removes camera shake',
 'camera shake reduction',
 'reduce camera shake',
 'reduces camera shake',
 'deshake',
 'de shake',
 'footage stabilization',
 'footage stabilisation',
 'smooth shaky video',
 'smooths shaky video',
 'smooth video',
 'smooths video',
 'stabilize camera motion',
 'stabilizes camera motion',
 'camera stabilization',
 'camera stabilisation',
 'image stabilization',
 'image stabilisation',
 'electronic image stabilization',
 'steady video',
 'steadies video',
 'steady footage',
 'shake free video',
 'shake free footage',
 'stabilize the video',
 'stabilizes the video',
 'stabilizes shaky footage',
 'stabilize shaky footage',
 'video shake removal')
EXPECTED_NEG = ('no video stabilization',
 'does not stabilize video',
 'does not stabilise video',
 'does not support video stabilization',
 'without video stabilization',
 'no video stabilizer',
 'does not do video stabilization',
 'does not perform video stabilization',
 'no camera shake removal',
 'does not remove camera shake',
 'does not support camera shake removal',
 'no footage stabilization',
 'does not stabilize footage',
 'no deshake',
 'does not deshake',
 'no image stabilization',
 'does not do image stabilization',
 'no camera stabilization',
 'does not stabilize camera motion',
 'video stabilization not supported',
 'no video smoothing',
 'does not smooth video',
 'no shaky video stabilization',
 'does not stabilize shaky video')
EXPECTED_GENERIC = ('stabilize_video',
 'stabilize_videos',
 'stabilize_footage',
 'stabilize_frames',
 'stabilize_camera',
 'stabilize_clip',
 'stabilize_stream',
 'stabilize_recording',
 'stabilize_motion',
 'remove_camera_shake',
 'remove_shake',
 'deshake',
 'de_shake',
 'video_stabilization',
 'video_stabilizer',
 'video_stabilize',
 'video_deshake',
 'camera_stabilization',
 'footage_stabilization',
 'smooth_video',
 'smooth_footage',
 'smooth_camera_motion',
 'remove_jitter',
 'jitter_removal')

class AuditTests(unittest.TestCase):
    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
        self.assertEqual(values['VIDEOSTABILIZATION'], EXPECTED_POS)
        self.assertEqual(values['NOVIDEOSTABILIZATION'], EXPECTED_NEG)
        self.assertEqual(values['GENERIC_NAMES'], EXPECTED_GENERIC)
        self.assertEqual((len(EXPECTED_POS), len(EXPECTED_NEG), len(set(EXPECTED_GENERIC))), (50,24,24))

    def fixture(self, docs='video stabilization', files=None, args=()):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'README.md').write_text(docs)
            for name, content in (files or {}).items():
                p=root/name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            out=io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code=main(['audit',d,'--json',*args])
            return code,json.loads(out.getvalue())

    def test_good_routes(self):
        for code in GOOD:
            with self.subTest(code=code):
                self.assertTrue(source_evidence(code))
                status,result=self.fixture(files={'app.py':code})
                self.assertEqual((status,result['verdict']), (0,'PASS'))

    def test_not_evidence(self):
        for code in BAD:
            with self.subTest(code=code):
                self.assertFalse(source_evidence(code))
                status,result=self.fixture(files={'app.py':code})
                self.assertEqual(status,2)
                self.assertEqual(result['findings'][0]['id'],'documented-video-stabilization-claim-false')
                self.assertEqual(result['findings'][0]['severity'],'HIGH')

    def test_all_phrases(self):
        for phrase in EXPECTED_POS:
            with self.subTest(phrase=phrase): self.assertEqual(self.fixture(phrase)[0],2)
        for phrase in EXPECTED_NEG:
            with self.subTest(phrase=phrase):
                self.assertEqual(self.fixture(phrase)[0],0)
                result=self.fixture(phrase, {'app.py':'x.deshake()'})
                self.assertEqual(result[0],2)
                self.assertEqual(result[1]['findings'][0]['id'],'documented-no-video-stabilization-claim-false')

    def test_generic_names(self):
        for name in EXPECTED_GENERIC:
            self.assertTrue(source_evidence('x.'+name+'()'))
            self.assertTrue(source_evidence('from pkg import '+name+' as operation; operation()'))
            self.assertFalse(source_evidence(name+'()'))

    def test_test_only(self):
        for path in ('tests/worker.py','test_app.py','app_test.py'):
            code,result=self.fixture(files={path:'x.deshake()'})
            self.assertEqual(code,0)
            self.assertEqual(result['findings'][0]['severity'],'MEDIUM')
            self.assertIn('message',result['findings'][0])
            self.assertEqual(self.fixture(files={path:'x.deshake()'},args=('--fail-on','medium'))[0],2)

    def test_docs(self):
        for fence in ('```','~~~','   ```'):
            self.assertEqual(self.fixture(fence+'\nvideo stabilization\n'+fence)[0],0)
        self.assertEqual(self.fixture('`video stabilization`')[0],2)
        self.assertEqual(self.fixture("doesn't stabilize video")[0],0)
        self.assertEqual(self.fixture('Unrelated prose',{'app.py':'x.deshake()'})[0],0)
        self.assertEqual(self.fixture('no video stabilization\n\nvideo stabilization')[0],2)

    def test_scope_exclusion_ignore(self):
        self.assertEqual(self.fixture(files={'a.py':'import vidstab; s=vidstab.VidStab()','b.py':'s.stabilize()'})[0],2)
        for prefix in ('docs','fixtures','examples'):
            self.assertEqual(self.fixture(files={prefix+'/a.py':'x.deshake()'})[0],2)
        self.assertEqual(self.fixture(files={'src/a.py':'x.deshake()'},args=('--ignore','src'))[0],2)
        self.assertEqual(self.fixture(files={'docs/a.md':'video stabilization'},docs='neutral')[0],2)
        self.assertEqual(self.fixture(files={'other/a.md':'video stabilization'},docs='neutral')[0],0)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            p=Path(d); (p/'README.md').write_text('video stabilization')
            (Path(e)/'a.py').write_text('x.deshake()')
            (p/'a.py').symlink_to(Path(e)/'a.py'); (p/'linked').symlink_to(e)
            self.assertEqual(audit(p)['findings'][0]['severity'],'HIGH')

    def test_cli(self):
        for args in ([],['bad'],['audit','/nonexistent-claim-audit-path'],['audit','--fail-on','HIGH'],['audit','--ignore','a','b']):
            with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(args),1)
        out=io.StringIO()
        with contextlib.redirect_stdout(out): self.assertEqual(main(['--version']),0)
        self.assertEqual(out.getvalue().strip(),'0.1.0')
        result=subprocess.run([sys.executable,'-m','video_stabilization_claim_audit','--version'],capture_output=True,text=True)
        self.assertEqual((result.returncode,result.stdout.strip()),(0,'0.1.0'))

GOOD = []
BAD = []

GOOD.extend(['import cv2; s=cv2.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; cv2.videostab.OnePassStabilizer().nextFrame()',
 'from cv2.videostab import OnePassStabilizer as C; s=C(); s.nextFrame()',
 'import cv2 as c; s=c.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; s=cv2.videostab.TwoPassStabilizer(); s.nextFrame()',
 'import cv2; cv2.videostab.TwoPassStabilizer().nextFrame()',
 'from cv2.videostab import TwoPassStabilizer as C; s=C(); s.nextFrame()',
 'import cv2 as c; s=c.videostab.TwoPassStabilizer(); s.nextFrame()',
 'import vidstab; s=vidstab.VidStab(); s.stabilize()',
 'import vidstab; vidstab.VidStab().stabilize()',
 'from vidstab import VidStab as C; s=C(); s.stabilize()',
 'import vidstab as lib; s: object=lib.VidStab(); s.stabilize()',
 'from vidstab import VidStab;\nwith VidStab() as s:\n s.stabilize()',
 'from vidstab import VidStab;\nasync def f():\n async with VidStab() as s:\n  s.stabilize()',
 'import vidstab; s=vidstab.VidStab(); s.stabilize_frame()',
 'import vidstab; vidstab.VidStab().stabilize_frame()',
 'from vidstab import VidStab as C; s=C(); s.stabilize_frame()',
 'import vidstab as lib; s: object=lib.VidStab(); s.stabilize_frame()',
 'from vidstab import VidStab;\nwith VidStab() as s:\n s.stabilize_frame()',
 'from vidstab import VidStab;\nasync def f():\n async with VidStab() as s:\n  s.stabilize_frame()',
 'import stabilo; s=stabilo.Stabilizer(); s.stabilize()',
 'import stabilo; stabilo.Stabilizer().stabilize()',
 'from stabilo import Stabilizer as C; s=C(); s.stabilize()',
 'import stabilo as lib; s: object=lib.Stabilizer(); s.stabilize()',
 'from stabilo import Stabilizer;\nwith Stabilizer() as s:\n s.stabilize()',
 'from stabilo import Stabilizer;\nasync def f():\n async with Stabilizer() as s:\n  s.stabilize()',
 'import cv2; cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); '
 'cv2.estimateAffinePartial2D(); cv2.warpAffine()',
 'from cv2 import goodFeaturesToTrack as f0, calcOpticalFlowPyrLK as f1, estimateAffinePartial2D '
 'as f2, warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffine2D(); '
 'cv2.warpAffine()',
 'from cv2 import goodFeaturesToTrack as f0, calcOpticalFlowPyrLK as f1, estimateAffine2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.SIFT_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()',
 'from cv2 import SIFT_create as f0, calcOpticalFlowPyrLK as f1, estimateAffinePartial2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.SIFT_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffine2D(); '
 'cv2.warpAffine()',
 'from cv2 import SIFT_create as f0, calcOpticalFlowPyrLK as f1, estimateAffine2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.ORB_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()',
 'from cv2 import ORB_create as f0, calcOpticalFlowPyrLK as f1, estimateAffinePartial2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.ORB_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffine2D(); '
 'cv2.warpAffine()',
 'from cv2 import ORB_create as f0, calcOpticalFlowPyrLK as f1, estimateAffine2D as f2, warpAffine '
 'as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.AKAZE_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()',
 'from cv2 import AKAZE_create as f0, calcOpticalFlowPyrLK as f1, estimateAffinePartial2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.AKAZE_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffine2D(); '
 'cv2.warpAffine()',
 'from cv2 import AKAZE_create as f0, calcOpticalFlowPyrLK as f1, estimateAffine2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.BRISK_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()',
 'from cv2 import BRISK_create as f0, calcOpticalFlowPyrLK as f1, estimateAffinePartial2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'import cv2; cv2.BRISK_create(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffine2D(); '
 'cv2.warpAffine()',
 'from cv2 import BRISK_create as f0, calcOpticalFlowPyrLK as f1, estimateAffine2D as f2, '
 'warpAffine as f3; f0(); f1(); f2(); f3()',
 'x.stabilize_video()',
 'x.remove_camera_shake()',
 'x.deshake()',
 'x.video_stabilization()',
 'x.stabilize_footage()',
 'from pkg import stabilize_video as s; s()'])
BAD.extend(['import cv2',
 'import vidstab',
 'import stabilo',
 'import other',
 'import cv2; s=cv2.videostab.OnePassStabilizer()',
 'import vidstab; s=vidstab.VidStab()',
 'import stabilo; s=stabilo.Stabilizer()',
 's.nextFrame()',
 's.stabilize()',
 'import stabilo; s=stabilo.Stabilizer(); s.set_ref_frame()',
 'import stabilo; s=stabilo.Stabilizer(); s.warp_cur_frame()',
 'import cv2; s=cv2.videostab.OnePassStabilizer(); s.setFrameSource(); s.setMotionEstimator()',
 'import vidstab; s=Other(); s.stabilize()',
 'from vidgear.gears import VideoGear; VideoGear(source, stabilize=True)',
 'import subprocess; subprocess.run(["ffmpeg", "vidstabdetect", "vidstabtransform"])',
 'import subprocess; subprocess.run(["Gyroflow"])',
 '"video stabilization" # x.deshake()',
 'x.deshake',
 'def broken(',
 'import vidstab; s=vidstab.VidStab(); s=Other(); s.stabilize()',
 'import cv2; cv2.goodFeaturesToTrack()',
 'import cv2; cv2.calcOpticalFlowPyrLK()',
 'import cv2; cv2.estimateAffinePartial2D()',
 'import cv2; cv2.estimateAffine2D()',
 'import cv2; cv2.warpAffine()',
 'import cv2; cv2.findHomography()',
 'import cv2; cv2.warpPerspective()',
 'import cv2; cv2.fastNlMeansDenoisingMulti()',
 'import cv2; cv2.VideoCapture()',
 'import cv2; cv2.VideoWriter()',
 'import cv2; cv2.absdiff()',
 'import cv2; cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); cv2.warpAffine()',
 'import cv2; cv2.goodFeaturesToTrack(); cv2.estimateAffinePartial2D(); cv2.warpAffine()',
 'import cv2; cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); cv2.warpAffine()',
 'import cv2; cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D()',
 'import cv2; import vidstab; import stabilo\ndef deshake(): pass\nx.deshake()',
 'import cv2; import vidstab; import stabilo\nclass Local:\n def deshake(self): pass\nx.deshake()',
 'import cv2; import vidstab; import stabilo\ndef stabilize_video(): pass\nx.stabilize_video()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def stabilize_video(self): pass\n'
 'x.stabilize_video()',
 'import cv2; import vidstab; import stabilo\n'
 'def VidStab(): pass\n'
 's=vidstab.VidStab(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def VidStab(self): pass\n'
 's=vidstab.VidStab(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'def Stabilizer(): pass\n'
 's=stabilo.Stabilizer(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def Stabilizer(self): pass\n'
 's=stabilo.Stabilizer(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'def OnePassStabilizer(): pass\n'
 's=cv2.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def OnePassStabilizer(self): pass\n'
 's=cv2.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; import vidstab; import stabilo\n'
 'def nextFrame(): pass\n'
 's=cv2.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def nextFrame(self): pass\n'
 's=cv2.videostab.OnePassStabilizer(); s.nextFrame()',
 'import cv2; import vidstab; import stabilo\n'
 'def stabilize(): pass\n'
 's=vidstab.VidStab(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def stabilize(self): pass\n'
 's=vidstab.VidStab(); s.stabilize()',
 'import cv2; import vidstab; import stabilo\n'
 'def warpAffine(): pass\n'
 'cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()',
 'import cv2; import vidstab; import stabilo\n'
 'class Local:\n'
 ' def warpAffine(self): pass\n'
 'cv2.goodFeaturesToTrack(); cv2.calcOpticalFlowPyrLK(); cv2.estimateAffinePartial2D(); '
 'cv2.warpAffine()'])
