import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT=Path(__file__).parents[1]

@unittest.skipUnless(shutil.which('swift'), 'Swift runtime required')
class MasterResumeTests(unittest.TestCase):
    def test_pause_resume_preserves_all_master_segments_and_new_session_is_separate(self):
        source=(ROOT/'tingdao-mix.swift').read_text()
        start=source.index('func openMasterOutput() {')
        end=source.index('\n///',start)
        with TemporaryDirectory() as temp:
            root=Path(temp)
            script=root/'test.swift'
            script.write_text('''import Foundation
var gMasterPath = CommandLine.arguments[1]
var gMasterOut: FileHandle?
func fail(_ message: String, _ code: Int32) -> Never { fatalError(message) }
'''+source[start:end]+'''
for segment in ["before pause", "after resume", "after second resume"] {
    openMasterOutput()
    gMasterOut!.write(segment.data(using: .utf8)!)
    gMasterOut!.closeFile()
}
gMasterPath = CommandLine.arguments[2]
openMasterOutput()
gMasterOut!.write("new session".data(using: .utf8)!)
gMasterOut!.closeFile()
''')
            old=root/'old.s16'; new=root/'new.s16'
            result=subprocess.run(['swift',str(script),str(old),str(new)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(old.read_bytes(),b'before pauseafter resumeafter second resume')
            self.assertEqual(new.read_bytes(),b'new session')
