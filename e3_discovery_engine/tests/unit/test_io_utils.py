import gzip
import tempfile
import unittest
from pathlib import Path

from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import (
    atomic_binary_path,
    atomic_text_writer,
    detect_delimiter,
    ensure_parent,
    json_dumps_sorted,
    open_text_auto,
    read_delimited,
    read_text,
    require_nonempty_file,
    sha256_file,
    text_stream,
    write_tsv,
)


class IoUtilsTests(unittest.TestCase):
    def test_ensure_parent_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b.txt"
            self.assertEqual(ensure_parent(path), path)
            self.assertTrue(path.parent.is_dir())

    def test_atomic_text_writer_publishes_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            with atomic_text_writer(path) as handle:
                handle.write("hello")
            self.assertEqual(path.read_text(), "hello")

    def test_atomic_text_writer_cleans_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            with self.assertRaises(RuntimeError):
                with atomic_text_writer(path) as handle:
                    handle.write("partial")
                    raise RuntimeError("stop")
            self.assertFalse(path.exists())

    def test_atomic_binary_path_publishes_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.bin"
            with atomic_binary_path(path) as temporary:
                temporary.write_bytes(b"abc")
            self.assertEqual(path.read_bytes(), b"abc")

    def test_atomic_binary_path_requires_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.bin"
            with self.assertRaises(DataValidationError):
                with atomic_binary_path(path) as temporary:
                    temporary.unlink()

    def test_open_text_auto_plain_and_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "a.txt"
            zipped = Path(tmp) / "a.txt.gz"
            plain.write_text("plain", encoding="utf-8")
            with gzip.open(zipped, "wt", encoding="utf-8") as handle:
                handle.write("gzip")
            with open_text_auto(plain) as handle:
                self.assertEqual(handle.read(), "plain")
            with open_text_auto(zipped) as handle:
                self.assertEqual(handle.read(), "gzip")

    def test_sha256_file_known_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_sha256_rejects_bad_chunk_size(self):
        with self.assertRaises(ValueError):
            sha256_file(Path(__file__), chunk_size=0)

    def test_detect_delimiter_csv_and_tsv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "a.csv"
            tsv_path = Path(tmp) / "a.tsv"
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            tsv_path.write_text("a\tb\n1\t2\n", encoding="utf-8")
            self.assertEqual(detect_delimiter(csv_path), ",")
            self.assertEqual(detect_delimiter(tsv_path), "\t")

    def test_read_delimited_preserves_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.tsv"
            path.write_text("a\tb\n1\t2\n", encoding="utf-8")
            self.assertEqual(read_delimited(path), [{"a": "1", "b": "2"}])

    def test_write_tsv_uses_union_of_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.tsv"
            count = write_tsv([{"a": 1}, {"a": 2, "b": 3}], path)
            self.assertEqual(count, 2)
            self.assertEqual(path.read_text().splitlines()[0], "a\tb")

    def test_json_dumps_sorted_is_deterministic(self):
        self.assertEqual(json_dumps_sorted({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_require_nonempty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a"
            path.write_text("x")
            self.assertEqual(require_nonempty_file(path), path)
            path.write_text("")
            with self.assertRaises(DataValidationError):
                require_nonempty_file(path)

    def test_read_text_and_text_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a"
            path.write_text("x", encoding="utf-8")
            self.assertEqual(read_text(path), "x")
        self.assertEqual(text_stream("y").read(), "y")


if __name__ == "__main__":
    unittest.main()
