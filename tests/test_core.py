import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from viralclip.core import Word, Candidate, check_url, make_candidates, write_captions, escape_ass

class TestCore(unittest.TestCase):
    def test_url_whitelist(self):
        check_url("https://www.youtube.com/watch?v=123")
        for url in ("http://youtube.com/", "https://127.0.0.1/private", "https://youtube.com.evil.com/video", "file:///etc/passwd"):
            with self.assertRaises(ValueError): check_url(url)
    def test_candidates(self):
        words = []
        for i in range(1800):
            text = "secret" if i % 40 == 0 else "useful"
            if i % 18 == 17: text += "."
            words.append(Word(i*.39, i*.39+.28, text))
        clips = make_candidates(words, 7, 25, 60, 710)
        self.assertEqual(len(clips), 7)
        self.assertTrue(all(c.end > c.start for c in clips))
        for i,c in enumerate(clips):
            for other in clips[i+1:]:
                overlap = max(0,min(c.end,other.end)-max(c.start,other.start))
                self.assertLess(overlap, .20*min(c.end-c.start,other.end-other.start))
    def test_captions(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"captions.ass"
            write_captions([Word(.2,.6,"hello"),Word(.7,1.0,"world")], Candidate(0,2,80,"a","b","c"),p)
            self.assertIn("Dialogue: 0",p.read_text())
            self.assertIn("hello",p.read_text())
            self.assertEqual(escape_ass("{hello}"),"(hello)")

if __name__ == "__main__": unittest.main()
