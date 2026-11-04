import tempfile
from pathlib import Path
import unittest

import run


class DirectiveTests(unittest.TestCase):
    def options(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.c"
            path.write_text(text)
            return run.source_options(path)

    def test_target_options_replace_default_without_overriding_o3(self):
        self.assertEqual(self.options('''
/* { dg-options "-O1 -w" } */
/* { dg-options "-mavx" { target { i?86-*-* x86_64-*-* } } } */
/* { dg-options "-O2 -fno-common" { target aarch64*-*-* } } */
'''), ["-fno-common"])

    def test_negated_target_and_nested_expression(self):
        with self.assertRaises(run.Unsupported):
            self.options('/* { dg-skip-if "needs x86" { ! { i?86-*-* x86_64-*-* } } } */')
        self.assertFalse(run.target_matches([["i?86-*-*", "x86_64-*-*"], "&&", "ilp32"]))
        self.assertTrue(run.target_matches(["aarch64*-*-*", "&&", "lp64"]))

    def test_unhandled_directive_is_not_silently_ignored(self):
        with self.assertRaises(run.Unsupported):
            self.options('/* { dg-additional-options "-ffast-math" } */')

    def test_empty_requirement_and_ignored_bitfield_option(self):
        for text in ('/* { dg-require-compat-dfp "" } */',
                     '/* { dg-options "-funsigned-bitfields" } */'):
            with self.assertRaises(run.Unsupported):
                self.options(text)

    def test_results_preserve_failure_and_reject_duplicates(self):
        self.assertEqual(run.parse_results("x/AA\t0\nx/AB\t134\n"), {"x/AA": 0, "x/AB": 134})
        with self.assertRaises(ValueError):
            run.parse_results("x/AA\t0\nx/AA\t0\n")


if __name__ == "__main__":
    unittest.main()
