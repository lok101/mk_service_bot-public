from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator

import pytest
from pymongo import MongoClient
from pymongo.database import Database
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

INTEGRATION_MONGODB_URI = os.environ.get("INTEGRATION_MONGODB_URI")
_MONGO_PORT = 27017


def _ping_mongo(uri: str) -> bool:
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
        return True
    except Exception:
        return False
    finally:
        client.close()


def _start_mongo_container() -> DockerContainer:
    container = (
        DockerContainer("mongo:7")
        .with_exposed_ports(_MONGO_PORT)
        .waiting_for(
            LogMessageWaitStrategy(
                re.compile(r"waiting for connections", re.IGNORECASE),
            ),
        )
    )
    container.start()
    return container


def _mongo_connection_url(container: DockerContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(_MONGO_PORT)
    return f"mongodb://{host}:{port}"


@pytest.fixture(scope="session")
def integration_mongodb_uri() -> Iterator[str]:
    if INTEGRATION_MONGODB_URI:
        if not _ping_mongo(INTEGRATION_MONGODB_URI):
            pytest.skip(
                f"INTEGRATION_MONGODB_URI is set but MongoDB is unreachable: "
                f"{INTEGRATION_MONGODB_URI}",
            )
        yield INTEGRATION_MONGODB_URI
        return

    try:
        container = _start_mongo_container()
    except Exception as error:
        pytest.skip(f"Could not start MongoDB test container: {error}")

    try:
        yield _mongo_connection_url(container)
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mongo_client(integration_mongodb_uri: str) -> Iterator[MongoClient]:
    client = MongoClient(integration_mongodb_uri)
    yield client
    client.close()


@pytest.fixture
def mongo_database(mongo_client: MongoClient) -> Iterator[Database]:
    database_name = f"mk_integration_{uuid.uuid4().hex}"
    database = mongo_client[database_name]
    yield database
    mongo_client.drop_database(database_name)
