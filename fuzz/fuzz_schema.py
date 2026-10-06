"""ClusterFuzzLite fuzz target: schema detection on hostile sqlite input."""

import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from devin_internals.schema import SchemaError, detect_schema_version


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    blob = fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 8192))
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        tmp.write(blob)
        tmp.flush()
        try:
            detect_schema_version(Path(tmp.name))
        except SchemaError:
            pass
        except Exception:
            pass


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
