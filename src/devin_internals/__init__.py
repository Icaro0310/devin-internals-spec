__version__ = "0.3.2"

from devin_internals.schema import (
    LATEST_KNOWN_SCHEMA,
    MIN_SUPPORTED_SCHEMA,
    VERIFIED_SCHEMA,
    SchemaDetectionError,
    SchemaError,
    UnknownSchemaVersionError,
    detect_schema_version,
)

__all__ = [
    "LATEST_KNOWN_SCHEMA",
    "MIN_SUPPORTED_SCHEMA",
    "VERIFIED_SCHEMA",
    "SchemaDetectionError",
    "SchemaError",
    "UnknownSchemaVersionError",
    "__version__",
    "detect_schema_version",
]
