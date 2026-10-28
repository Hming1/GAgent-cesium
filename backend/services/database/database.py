import logging

from core.config import GEODATA_DATABASE_URL

# Try to import psycopg_pool, handle missing dependency gracefully
try:
    from psycopg_pool import AsyncConnectionPool

    PSYCOPG_AVAILABLE = True
except ImportError:
    AsyncConnectionPool = None
    PSYCOPG_AVAILABLE = False

# Initialize connection pool as None
db_pool = None
# Track if database initialization failed
db_initialization_failed = False

logger = logging.getLogger(__name__)


def _normalize_conninfo(url: str) -> str:
    """Normalize a SQLAlchemy-style DB URL to a plain libpq conninfo for psycopg."""
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgis://", "postgresql://"
    )


async def init_db():
    """Initialize the async pool for the geodata / dataset-catalog database.

    This pool backs the librarian dataset search (``dataset_resources_search``)
    and other user-independent geospatial queries, so it follows
    ``GEODATA_DATABASE_URL`` rather than the main application ``DATABASE_URL``.
    """
    global db_pool, db_initialization_failed
    if db_pool is None and not db_initialization_failed:  # Ensure we only initialize once
        try:
            if not PSYCOPG_AVAILABLE:
                logger.warning(
                    "psycopg_pool is not available. Database features will be unavailable. "
                    "Install psycopg[pool] to enable database functionality."
                )
                db_initialization_failed = True
                return

            if not GEODATA_DATABASE_URL:
                logger.warning(
                    "GEODATA_DATABASE_URL (or DATABASE_URL) is not set. "
                    "Geodata/catalog database features will be unavailable."
                )
                db_initialization_failed = True
                return

            # Type guard to ensure AsyncConnectionPool is available
            if AsyncConnectionPool is None:
                raise RuntimeError("AsyncConnectionPool is not available")

            conninfo = _normalize_conninfo(GEODATA_DATABASE_URL)
            db_pool = AsyncConnectionPool(conninfo=conninfo, min_size=1, max_size=10)
            await db_pool.open()  # Ensure the pool is open
            logger.info("Geodata database connection pool initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize geodata database connection pool: {e}")
            db_initialization_failed = True
            db_pool = None


async def close_db():
    """Close the async database pool."""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None


# Dependency function for FastAPI
async def get_db():
    """Provide an async database connection."""
    if db_initialization_failed:
        raise RuntimeError(
            "Geodata database is not available. Please check your GEODATA_DATABASE_URL "
            "environment variable and ensure the database server is accessible."
        )
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized!")
    async with db_pool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur


def is_database_available() -> bool:
    """Check if the database is available for use."""
    return db_pool is not None and not db_initialization_failed
