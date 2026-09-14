import pytest
from pathlib import Path
from sqlalchemy import create_engine
from app.db import Base

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield url


@pytest.fixture
def real_data_dir():
    return str(Path(__file__).parent.parent.parent / "data" / "deliveries")


@pytest.fixture(scope="module")
def real_data_dir_module():
    return str(Path(__file__).parent.parent.parent / "data" / "deliveries")


@pytest.fixture
def fixture_dir():
    return str(FIXTURES)
