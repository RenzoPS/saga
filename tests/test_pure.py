"""Tests de las funciones puras del paquete vc/ (sin audio/red/subprocess).

Correr:  .venv/bin/python -m unittest tests.test_pure   (desde la raíz del proyecto)
     o:  .venv/bin/python tests/test_pure.py
"""

import sys
import unittest
from pathlib import Path

# permitir `python tests/test_pure.py` desde cualquier cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vc.tts import clean_for_tts, _next_chunk_cut, _HARD_PUNCT_CHARS  # noqa: E402
from vc.session import is_reset_command, is_visual_command  # noqa: E402


class TestCleanForTTS(unittest.TestCase):
    def test_strips_markdown_keeps_content(self):
        self.assertEqual(clean_for_tts("**hola** `code` y *eso*"), "hola code y eso")

    def test_removes_code_blocks(self):
        self.assertEqual(clean_for_tts("antes ```py\nx=1\n``` despues"), "antes despues")

    def test_collapses_whitespace(self):
        self.assertEqual(clean_for_tts("a\n\nb   c"), "a. b c")


class TestSessionKeywords(unittest.TestCase):
    def test_reset_positive(self):
        self.assertTrue(is_reset_command("dale, nueva sesión"))
        self.assertTrue(is_reset_command("empezamos de cero"))

    def test_reset_negative(self):
        self.assertFalse(is_reset_command("contame algo de la sesión de ayer"))

    def test_visual_word_boundary(self):
        self.assertTrue(is_visual_command("mirá esto"))
        self.assertTrue(is_visual_command("mostrame la pantalla"))
        self.assertFalse(is_visual_command("admira el cielo"))  # 'mira' embebido no matchea


class TestChunkCut(unittest.TestCase):
    def test_cuts_on_hard_punct(self):
        buf = "Hola mundo. Esto sigue"
        cut = _next_chunk_cut(buf)
        self.assertIsNotNone(cut)
        self.assertTrue(buf[:cut].rstrip()[-1] in _HARD_PUNCT_CHARS)

    def test_no_cut_when_short(self):
        self.assertIsNone(_next_chunk_cut("hola"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
