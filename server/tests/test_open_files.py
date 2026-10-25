"""earthd.raise_open_files: the open files soft limit raised to the hard one (GitHub #99)."""
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import earthd  # noqa: E402


class OpenFilesTest(unittest.TestCase):
    def test_raised_to_the_hard_limit_at_most_open_files(self):
        try:
            import resource
        except ImportError:
            self.skipTest("no resource module (Windows)")
        calls = []
        with unittest.mock.patch.object(resource, "getrlimit", return_value=(1024, 1048576)), \
                unittest.mock.patch.object(resource, "setrlimit", side_effect=lambda k, v: calls.append(v)):
            earthd.raise_open_files()
        self.assertEqual(calls, [(earthd.OPEN_FILES, 1048576)])
        calls.clear()
        with unittest.mock.patch.object(resource, "getrlimit", return_value=(1024, 4096)), \
                unittest.mock.patch.object(resource, "setrlimit", side_effect=lambda k, v: calls.append(v)):
            earthd.raise_open_files()
        self.assertEqual(calls, [(4096, 4096)], "never over the hard limit")
        calls.clear()
        with unittest.mock.patch.object(resource, "getrlimit", return_value=(100000, 1048576)), \
                unittest.mock.patch.object(resource, "setrlimit", side_effect=lambda k, v: calls.append(v)):
            earthd.raise_open_files()
        self.assertEqual(calls, [], "a higher soft limit is left as it is")


if __name__ == "__main__":
    unittest.main()
